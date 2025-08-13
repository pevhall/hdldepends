# vi: foldmethod=marker
import os
import re
import sys
import glob
import json
import pickle
import string
import fnmatch
import argparse
import subprocess
import xml.etree.ElementTree as xml_et

tomllib = None
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        pass

yaml = None
try:
    import yaml
except ModuleNotFoundError:
        pass


from pathlib import Path
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Union, List, Tuple, Set, Dict


#created own crapy logger because logging doesn't work with f strings {{{

log_level = 0

class log:
    @staticmethod
    def _log(severity, *args, **kwargs):
        print(f'[{severity}]', *args, **kwargs, file=sys.stderr)

    @staticmethod
    def error(*args, **kwargs):
        log._log('ERROR', *args, **kwargs)

    @staticmethod
    def warning(*args, **kwargs):
        if log_level >= 0:
            log._log('WARNING', *args, **kwargs)

    @staticmethod
    def info(*args, **kwargs):
        if log_level >= 1:
            log._log('INFO', *args, **kwargs)

    @staticmethod
    def debug(*args, **kwargs):
        if log_level >= 2:
            log._log('DEBUG', *args, **kwargs)
#}}}

TOML_KEY_VER_SEP = '@'

HDL_DEPENDS_VERSION_NUM = 10

# Utility functions {{{
def path_abs_from_dir(dir: Path, loc: Path):
    loc_str = str(loc).format(**os.environ)
    if re.search(r"\{[^}]+\}", loc_str):
        log.error('Note: program does not currently support curly brackets, {}, in path it expects these to make environment variables')
        raise RuntimeError(f"Path {loc_str} still contains env variables which we cannot find in shell's env")
    loc = Path(loc_str)
    # dir = Path(os.path.expandvars(str(dir)))
    if not loc.is_absolute():
        loc = dir / loc
        loc = loc.resolve()
    return loc

def resolve_abs_path(dir: Path):
    if not dir.is_absolute():
        dir = dir.resolve()
    return dir

def get_file_modification_time(f: Path):
    return f.lstat().st_mtime

def str_to_name(s: str):
    l = s.split(".")
    if len(l) == 1:  # no lib use default
        return Name(LIB_DEFAULT, name=l[0])
    elif len(l) == 2:
        return Name(lib=l[0], name=l[1])
    else:
        raise Exception(f"ERROR converting str {s} to Name")

def contains_any(a: List, b: List) -> bool:
    for aa in a:
        if aa in b:
            return True
    return False

def key_split_opt_ver(k : str) -> Tuple[str, Optional[str]]:
    split_k = k.split(TOML_KEY_VER_SEP)
    lsk = len(split_k)
    if not (lsk == 1 or lsk == 2):
        raise Exception(f'ERROR: key {k}, can only have upto 1 {TOML_KEY_VER_SEP}')
    ver = None
    if lsk == 2:
        ver = split_k[1]
    return split_k[0], ver



def keys_rm_opt_ver( keys : List[str]) -> List[str]:
    return [key_split_opt_ver(k)[0]  for k in keys ]

def issue_key(good_keys: List, keys: List) -> Optional[str]:
    for k in keys:
        if not k in good_keys:
            return k
    return None

def make_list(v) -> List:
    if isinstance(v, List):
        return v
    else:
        return [v]


def make_set(v) -> Set:
    if isinstance(v, Set):
        return v
    else:
        return set(v)

def read_text_file_contents(loc : Path):

    encodings = ['utf-8', 'iso-8859-1','windows-1251', 'windows-1252' ,'gb2312' ,'utf-16']
    for enc in encodings:
        try:
            log.debug(f'Opening {loc} with encoding {enc}')
            with open(loc, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            log.debug(f'Trying next codec')
    log.debug(f'Could not open {loc} with one of these {encodings}')
    raise RuntimeError(f'Could not decode file {loc}')


# }}}

def process_glob_patterns(patterns: List[str], base_path: Path = Path(".")) -> List[Path]: # {{{
    """
    Process a list of glob patterns sequentially, including exclusion patterns (starting with '!'),
    to generate a filtered list of file paths. Each pattern modifies the current file list.

    Args:
        patterns (List[str]): list of glob patterns. Patterns starting with '!' are exclusions.
        base_path (str): Base directory to start glob searches from. Defaults to current directory.

    Returns:
        List[str]: list of absolute file paths that match the inclusion patterns but not the exclusion patterns.

    Example:
        patterns = [
            "*.py",          # Include all Python files
            "test/*.py",     # Include additional Python files in test directory
            "!**/temp*"      # Exclude any files with temp in the name from current list
        ]
        files = process_glob_patterns(patterns)
    """
    base_path = resolve_abs_path(base_path) # Get absolute path of base directory
    current_files = set()

    # Process patterns sequentially
    for pattern in patterns:
        if pattern.startswith('!'):
            # Handle exclusion pattern - remove matching files from current set
            exclude_pattern = pattern[1:]  # Remove the '!' character

            # Convert glob pattern to fnmatch pattern
            # Replace '**/' with '*/' for deep matching
            fnmatch_pattern = exclude_pattern.replace('**/', '*/')

            # Filter out matching files from current set
            current_files = {
                f for f in current_files
                if not fnmatch.fnmatch(f, fnmatch_pattern)
            }
        else:
            # Handle inclusion pattern - add new matching files
            matched_files = glob.glob(str(base_path / pattern), recursive=True)
            current_files.update(resolve_abs_path(Path(f)) for f in matched_files)

    # Return sorted list of absolute paths
    return sorted(current_files)
# }}}

class Name: # {{{
    lib: str
    name: Optional[str]

    def __init__(self, lib, name):
        self.lib = lib.lower() #VHDL case insenstive
        if name is not None:
            self.name = name.lower() #VHDL case insenstive
        else:
            self.name = None

    def __repr__(self):
        if self.name is not None:
            return f"{self.lib}.{self.name}"
        return f"{self.lib}.*"

    def __eq__(self, other):
        if self.lib != other.lib:
            return False
        if self.name is None or other.name is None:
            return True  # True if name is enitre library
        return self.name == other.name

    def __hash__(self):
        return hash((self.lib, self.name))
#}}}

class Lookup: #{{{
    def __init__(self):
        self.ignore_components : set[str] = set()
        self.x_tool_version = ''
        self.x_device = ''

    def get_vhdl_package(self, name: Name, f_obj_required_by : Optional["FileObjVhdl"]) -> Optional["FileObjVhdl"]:
        raise Exception("Virtual called")

    def get_entity(self, name: Name, f_obj_required_by : Optional["FileObj"]) -> Optional["FileObj"]:
        raise Exception("Virtual called")

    def add_loc(self, loc: Path, f_obj: "FileObj"):
        pass

    def add_entity(self, name: Name, f_obj: "FileObj"):
        pass

    def check_if_skip_from_order(self, loc:Path)->bool:
        raise Exception("Virtual called")

    def add_verilog_file_name(self, file_name: str, f_obj : "FileObjVerilog"):
        pass

    def add_vhdl_package(self, name: Name, f_obj: "FileObjVhdl"):
        pass

    def write_file_list(self, f_loc, f_type : Optional["FileObjType"]=None, lib : Optional[str] = None):
        pass

    def write_ext_file_list(self, f_loc : Path, tag : Optional[str] = None):
        pass

    def has_top_file(self) -> bool:
        return False

    def set_x_tool_version(self, x_tool_version : str):
        if len(self.x_tool_version) != 0:
            if x_tool_version != self.x_tool_version:
                log.warning(f'Lookup::set_x_tool_version({x_tool_version}) was previously {self.x_tool_version}')
            else:
                log.info(f'Lookup::set_x_tool_version({x_tool_version}) set to the same value twice')
        else:
            log.debug(f'Lookup::set_x_tool_version({x_tool_version})')
        self.x_tool_version = x_tool_version

    def set_x_device(self, x_device : str):
        if len(self.x_device) != 0:
            if x_device != self.x_device:
                log.warning(f'Lookup::set_x_device({x_device}) was previously {self.x_device}')
            else:
                log.info(f'Lookup::set_x_device({x_device}) set to the same value twice')
        else:
            log.debug(f'Lookup::set_x_device({x_device})')
        self.x_device = x_device

#}}}

# Constructs to handle files {{{

LIB_DEFAULT = 'work'

class FileObjType(Enum):
    VHDL = auto()
    VERILOG = auto()
    OTHER = auto()
    X_BD = auto()
    X_XCI = auto()
    DIRECT = auto()


def string_to_FileObjType(s: str) -> FileObjType:
    try:
        return FileObjType[s.upper()]
    except KeyError:
        raise ValueError(f"Unknown file type: {s}")

class FileObj:
    def __init__(self, loc: Path, ver : Optional[str]=None):
        self.loc = resolve_abs_path(loc)
        self.lib = None #LIB_DEFAULT
        self.entities: List[Name] = []
        self.entity_deps: List[Name] = []
        self.modification_time =  self.get_modification_time_on_disk()
        self.f_type : Optional[FileObjType] = None
        self.level = None
        self.ver = ver
        self.direct_deps : List = []
        self.x_tool_version = ''
        self.x_device = ''

    def requires_update(self):
        return self.get_modification_time_on_disk() != self.modification_time

    def get_modification_time_on_disk(self):
        return get_file_modification_time(self.loc)

    def replace(self, f_obj : 'FileObj'):
        self.__dict__.update(f_obj.__dict__) #this didn't work

    @property
    def file_type_str(self) -> str:
        return "Unknown"

    @property
    def file_type_str_w_ver_tag(self) -> str:
        class_str = self.file_type_str
        if self.ver is None:
            return class_str
        return class_str + TOML_KEY_VER_SEP + self.ver

    @property
    def ver_tag(self) -> Optional[str]:
        return self.ver

    @staticmethod
    def _add_to_f_deps(file_deps, f_obj):
        if f_obj not in file_deps:
            file_deps.append(f_obj)

    def register_with_lookup(self, look: Lookup, skip_loc : bool = False):
        for e in self.entities:
            look.add_entity(e, self)
        if not skip_loc:
            look.add_loc(self.loc, self)

    def get_file_deps(self, look: Lookup) -> List['FileObj']:
        file_deps = []
        for e in self.entity_deps:
            f_obj = look.get_entity(e, self)
            if f_obj is not None:
                self._add_to_f_deps(file_deps, f_obj)

        return file_deps

    def parse_file_again(self)->"FileObj":
        raise Exception("must be overloaded should be unreachable")

    def equivalent(self, other : "FileObj"):
        result = (self.loc == other.loc
                  and self.lib == other.lib
                  and self.entities == other.entities
                  and self.entity_deps == other.entity_deps
                  and self.f_type == other.f_type
                  and self.ver == other.ver
                  )
        return result

    def _get_compile_order(
        self, look: Lookup, files_passed=[], components_missed=[], level=0
    ) -> List['FileObj']:
        files_passed.append(self)
        if look.check_if_skip_from_order(self.loc):
        # if self.loc in look.files_2_skip_from_order:
            return []
        order: List[FileObj] = []
        for f_obj in self.get_file_deps(look):
            if f_obj not in files_passed:
                order += f_obj._get_compile_order(look, files_passed, components_missed = components_missed, level = level + 1)

        for ddep in self.direct_deps:
            ddep.level = level+1
            order.append(ddep)
        order.append(self)
        self.level = level
        return order

    def get_compile_order(self, look: Lookup) -> List['FileObj']:
        return self._get_compile_order(look)

    def update(self) -> Tuple[bool, bool]:
        """Returns True if the dependencies have changed, Returns True if file was modified"""
        if self.requires_update():
            f_obj = self.parse_file_again()
            equivalent = f_obj.equivalent(self)
            if equivalent:
                log.info(f'file {self.loc} updated but dependencies remain unchanaged')
                self.modification_time = f_obj.modification_time
                return False, True
            else:
                log.info(f'file {self.loc} is updated and dependencies have changed')
                self.replace(f_obj)

                return True, True
        return False, False


class FileObjOther(FileObj):
    def __init__(self, loc: Path, ver : Optional[str]):
        super().__init__(loc, ver)
        self.f_type : Optional[FileObjType] = FileObjType.OTHER

    @property
    def file_type_str(self) -> str:
        return "Other"

    def parse_file_again(self)->FileObj:
        return self

class FileObjDirect(FileObj):
    def __init__(self, loc: Path, ver : Optional[str]):
        super().__init__(loc, ver)
        self.f_type : Optional[FileObjType] = FileObjType.DIRECT

    @property
    def file_type_str(self) -> str:
        return "Direct"

    def parse_file_again(self)->FileObj:
        return self

class FileObjX(FileObj):
    def __init__(self, loc: Path, ver : Optional[str], x_tool_version : str, x_device : str):
        super().__init__(loc, ver)
        self.x_tool_version = x_tool_version
        self.x_device = x_device

class FileObjXBd(FileObjX):
    def __init__(self, loc: Path, ver : Optional[str], x_tool_version : str, x_device : str):
        super().__init__(loc, ver, x_tool_version, x_device)
        self.f_type : Optional[FileObjType] = FileObjType.X_BD

    @property
    def file_type_str(self) -> str:
        return "X_BD"

    def parse_file_again(self)->FileObj:
        assert self.loc is Path
        assert self.ver is str or self.ver is None
        return parse_x_bd_file(None, loc=self.loc, ver=self.ver)

class FileObjXXci(FileObjX):
    def __init__(self, loc: Path, ver : Optional[str], x_tool_version : str, x_device : str):
        super().__init__(loc, ver, x_tool_version, x_device)
        self.f_type : Optional[FileObjType] = FileObjType.X_XCI

    @property
    def file_type_str(self) -> str:
        return "X_XCI"

    def parse_file_again(self)->FileObj:
        assert self.loc is Path
        assert self.ver is str or self.ver is None
        return parse_x_xci_file(None, loc=self.loc, ver=self.ver)

class FileObjVerilog(FileObj):

    @dataclass
    class VInc:
        name : str
        is_sys : bool

    def __init__(self, loc: Path, ver : Optional[str]):
        super().__init__(loc, ver)
        self.verilog_includes : List[FileObjVerilog.VInc] = []
        self.f_type : Optional[FileObjType] = FileObjType.VERILOG

    @property
    def file_type_str(self) -> str:
        return "Verilog"

    def register_with_lookup(self, look: Lookup, skip_loc : bool = False):
        super().register_with_lookup(look, skip_loc)
        look.add_verilog_file_name(self.loc.name, self)

    def get_file_deps(self, look: Lookup) -> List[FileObj]:
        file_deps = super().get_file_deps(look)
        # file_deps += self.get_verilog_include_deps(look)
        return file_deps

    def get_verilog_include_deps(self, look : Lookup) -> List[FileObj]:
        raise Exception("TODO!!!")
        # file_deps = []
        #
        # for name, is_sys in self.verilog_includes:
        #     f_obj = look.get_verilog_file(name, self)
        #     if f_obj is not None:
        #         self._add_to_f_deps(file_deps, f_obj)
        #     else:
        #         if is_sys:
        #             log.warning('could not find sys include')
        #         else:
        #             log.error('could not find sys include')
        # return file_deps

    def parse_file_again(self)->FileObj:
        assert self.ver is str or self.ver is None
        return parse_verilog_file(None, loc=self.loc, ver=self.ver)


    def equivalent(self, other : FileObj):
        if not isinstance(other, FileObjVerilog):
            return False

        result = (self.verilog_includes == other.verilog_includes)
        if not result:
            return result

        return FileObj.equivalent(self, other)


class FileObjVhdl(FileObj):

    def __init__(self, loc: Path, lib: str, ver:Optional[str]):
        super().__init__(loc, ver=ver)
        self.lib = lib
        self.vhdl_packages: List[Name] = []
        self.vhdl_component_decl: List[str] = []
        self.vhdl_component_deps: List[str] = []
        self.vhdl_package_deps: List[Name] = []
        self.f_type : Optional[FileObjType] = FileObjType.VHDL

    @property
    def file_type_str(self):
        return "VHDL"

    def register_with_lookup(self, look: Lookup, skip_loc : bool = False):
        super().register_with_lookup(look, skip_loc)
        for p in self.vhdl_packages:
            look.add_vhdl_package(p, self)


    def get_file_deps(self, look: Lookup, components_missed = []) -> List[FileObj]:
        file_deps = super().get_file_deps(look)
        file_deps += self.get_vhdl_package_deps(look)

        if len(self.vhdl_component_deps) > 0:
            file_package_deps = self.get_vhdl_package_deps(look)
            for component in self.vhdl_component_deps:
                if component in look.ignore_components:
                    continue
                found = False
                f_obj = None
                try:
                    f_obj = look.get_entity(Name(self.lib, component), self)
                except KeyError:
                    pass
                if f_obj is None:
                    try:
                        f_obj = look.get_entity(Name(LIB_DEFAULT, component), self)
                    except KeyError:
                        pass
                if f_obj is not None:
                    found = True
                    file_deps.append(f_obj)
                else:
                    for f_obj in file_package_deps:
                        if isinstance(f_obj, FileObjVhdl):
                            if component in f_obj.vhdl_component_decl:
                                found = True
                                break
                if not found:
                    if component not in components_missed:
                        log.warning(f'File {self.loc} cannot find component declartion for component dependency {component}')
                        components_missed.append(component)
        return file_deps
    def get_vhdl_package_deps(self, look : Lookup) -> List[FileObj]:
        file_deps = []

        for p in self.vhdl_package_deps:
            f_obj = look.get_vhdl_package(p, self)
            if f_obj is not None:
                self._add_to_f_deps(file_deps, f_obj)
        return file_deps

    def parse_file_again(self)->FileObj:
        return parse_vhdl_file(None, self.loc, self.lib, self.ver)


    def equivalent(self, other : FileObj):
        if not isinstance(other, FileObjVhdl):
            return False

        result = (self.vhdl_packages == other.vhdl_packages
            and self.vhdl_package_deps == other.vhdl_package_deps)

        if not result:
            return result

        return FileObj.equivalent(self, other)

class ConflictFileObj:
    def __init__(self, conflict_list: List[FileObj]):
        self.loc_2_file_obj: dict[Path, FileObj] = {}
        for conflict in conflict_list:
            self.add_f_obj(conflict)

    def add_f_obj(self, f_obj: FileObj):
        if f_obj.loc in self.loc_2_file_obj:
            raise Exception(f"ERROR tried to add the same file twice to confict, {f_obj.loc}")
        self.loc_2_file_obj[f_obj.loc] = f_obj

    def log_confict(self, key):

        can_filter_on_version = True
        for loc, f_obj in self.loc_2_file_obj.items():
            if len(f_obj.x_tool_version) == 0:
                can_filter_on_version = False

        log.error(f"Conflict on key {key} could not resolve between")
        log.error(f"  (please resolve buy adding the one of the files to the prject toml):")
        if can_filter_on_version:
            log.error(f"  (or you can filter using x_tool_version)")
        for loc, f_obj in self.loc_2_file_obj.items():
            x_info = ''
            if len(f_obj.x_tool_version) != 0 or len(f_obj.x_device) != 0:
                x_info = f' ({f_obj.x_tool_version} {f_obj.x_device})'
            log.error(f"\t{loc}{x_info}")

    def get_f_objs(self):
        return self.loc_2_file_obj.values()

    def resolve_conflict(self, x_tool_version : str, x_device : str) -> Optional[FileObj]:
        log.debug(f'resolve_conflict ({x_tool_version}, {x_device})')
        if len(x_tool_version) == 0 or len(x_device) == 0:
            return None
        chosen = None
        got_version = False
        matched = False
        for f_obj in self.loc_2_file_obj.values():
            if len(f_obj.x_tool_version) == 0 or len(f_obj.x_device) == 0:
                return None

            f_obj_got_version = x_tool_version == f_obj.x_tool_version
            f_obj_matched = got_version and x_device == f_obj.x_device

            if f_obj_matched and matched:
                log.error(f'Got a x_tool_version and x_device match for both files {f_obj.loc} and {chosen.loc} cannot resolve this issue')
                return None

            if x_tool_version < f_obj.x_tool_version:
                log.debug(f'File {f_obj.loc} x_tool_version to low got {f_obj.x_tool_version} wanted {x_tool_version}')
                continue

            if chosen is not None:
                if f_obj.x_tool_version < chosen.x_tool_version:
                    continue
                if f_obj.x_tool_version == chosen.x_tool_version:
                    if f_obj.x_device != x_device:
                        continue

            got_version = f_obj_got_version
            f_obj_matched = f_obj_matched
            chosen = f_obj
            if matched:
                break

        if not got_version:
            log.warning(f'File has x_tool_version got {chosen.x_tool_version} but wanted {x_tool_version} please create an updated version')
        else:
            log.warning(f'File has correct version but wrong x_device got {chosen.x_device} but wanted {x_device} please create an updated version')

        return chosen


FileObjLookup = Union[ConflictFileObj, FileObj]

# }}}

# VHDL file parsing {{{
def vhdl_remove_comments(vhdl_code: str) -> str:
    # Remove single-line comments
    code_without_single_comments = re.sub(r'--.*$', '', vhdl_code, flags=re.MULTILINE)

    # Remove multi-line comments
    code_without_comments = re.sub(r'/\*.*?\*/', '', code_without_single_comments, flags=re.DOTALL)

    return code_without_comments

def vhdl_remove_protected_code(vhdl_code:str) -> str:
    """Removes protected code from VHDL code.

    Args:
        vhdl_code (str): Single string of VHDL code from file read.

    Returns:
        str: Single string of VHDL code without any protected code
    """
    code = vhdl_code.strip()
    lines = code.splitlines()
    dict_lines = dict.fromkeys(lines)
    protected_end = "`protect end_protected"
    if protected_end in dict_lines:
        end_of_protected_idx = list(dict_lines.keys()).index(protected_end) + 1
        if end_of_protected_idx >= len(lines):
            return ""
        else:
            return "\n".join(lines[end_of_protected_idx:])
    else:
        return vhdl_code

vhdl_regex_patterns = {
    "package_decl": re.compile(
        r"(?<!:)\bpackage\s+(\w+)\s+is.*?end(?:\s+(?:package|\1)|;)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "entity_decl": re.compile(
        r"(?<!:)\Wentity\s+(\w+)\s+is.*?end\s+(?:entity|\1|;)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "vhdl_component_decl": re.compile(
        r"(?<!:)\Wcomponent\s+(\w+)\s+(?:is|).*?end\s+(?:component|\1|;)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "component_inst": re.compile(
        r"\s*(\w+)\s*:\s*(\w+)(?:\s*generic\s*map\s*\(.*?\))?\s*port\s*map\s*\(.*?\)\s*;",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "direct_inst": re.compile(
        r"\s*(\w+)\s*:\s*(?:entity\s+)?(\w+)\.(\w+)(?:\s*generic\s*map\s*\(.*?\))?\s*port\s*map\s*\(.*?\)\s*;",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "package_use": re.compile(
        r"\buse\s+(\w+)\.(\w+)\.\w+\s*;", re.IGNORECASE | re.MULTILINE
    ),
    "c_coef_file": re.compile(
        r'_?attribute\s+C_COEF_FILE?\s+of\s+(\w+)\s*:\s*label\s+is\s+"([^"]+)"\s*;', re.IGNORECASE
    ),
    "is_du_within_envelope": re.compile(
        r'_?attribute\s+is_du_within_envelope?\s+of\s+(\w+)\s*:\s*label\s+is\s+"true"\s*;', re.IGNORECASE
    )
}

def parse_vhdl_file(look: Optional[Lookup], loc: Path, lib=LIB_DEFAULT, ver=None) -> FileObjVhdl:
    """ Function to find matches in the VHDL code """

    log.info(f"passing VHDL file {lib:} {loc}:")
    vhdl = read_text_file_contents(loc)

    vhdl = vhdl_remove_comments(vhdl)
    vhdl = vhdl_remove_protected_code(vhdl)
    f_obj = FileObjVhdl(loc, lib=lib, ver=ver)
    folder = loc.parent

    deps_inst_dict_comp = {}
    deps_inst_dict_direct = {}
    deps_inst_to_remove = []
    matches = {}
    for key, pattern in vhdl_regex_patterns.items():
        matches[key] = pattern.findall(vhdl)
    for construct, found in matches.items():
        if construct == "package_decl":
            for item in found:
                name = Name(lib, item)
                if name not in f_obj.vhdl_packages:
                    log.debug(f'VHDL {loc} declares package {name}')
                    f_obj.vhdl_packages.append(name)
        elif construct == "entity_decl":
            for item in found:
                name = Name(lib, item)
                if name not in f_obj.entities:
                    f_obj.entities.append(name)
                    log.debug(f'VHDL {loc} component decared {name}')
        elif construct == "vhdl_component_decl":
            for item in found:
                component = item
                if component not in f_obj.vhdl_component_decl:
                    log.debug(f'VHDL {loc} component decared {component}')
                    f_obj.vhdl_component_decl.append(component)
        elif construct == "component_inst":
            for item in found:
                inst = item[0]
                component = item[1]
                deps_inst_dict_comp[inst] = component
                if component not in f_obj.vhdl_component_deps:
                    log.debug(f'VHDL {loc} component {component}')
                    f_obj.vhdl_component_deps.append(component)
        elif construct == "direct_inst":
            for item in found:
                inst = item[0]
                l = item[1]
                if l == LIB_DEFAULT:
                    l = lib
                name = Name(l, item[2])
                deps_inst_dict_direct[inst] = name
                if name not in f_obj.entity_deps:
                    log.debug(f'VHDL {loc} requires {name}')
                    f_obj.entity_deps.append(name)
        elif construct == "package_use":
            for item in found:
                l = item[0]
                if l == LIB_DEFAULT:
                    l = lib
                name = Name(l, item[1])
                if name not in f_obj.vhdl_package_deps:
                    f_obj.vhdl_package_deps.append(name)
                    log.debug(f'VHDL {loc} requires package {name}')
                    log.debug(
                        f"\tpackage_use {name}"
                    )  # Extract library and package names`
        elif construct == "c_coef_file":
            for item in found:
                # instance = item[0]
                f_str = item[1]
                log.debug(f'VHDL {loc} coefficent file {f_str}')
                direct_dep_loc = folder/f_str
                f_obj.direct_deps.append(FileObjDirect(direct_dep_loc,ver=ver))
        elif construct == "is_du_within_envelope":
            for item in found:
                instance = item
                log.debug(f'VHDL {loc} ecrypted instance {instance}')
                deps_inst_to_remove.append(instance)
        else:
            raise Exception(f"error construct '{construct}'")

    for inst_rm in deps_inst_to_remove:
        log.debug(f'VHDL {loc} removeinb ecrypted instance {inst_rm}')
        if inst_rm in deps_inst_dict_comp:
            comp = deps_inst_dict_comp[inst_rm]
            f_obj.vhdl_component_deps.remove(comp)
        elif inst_rm in deps_inst_dict_direct:
            name = deps_inst_dict_direct[inst_rm]
            f_obj.entity_deps.remove(name)
        else:
            log.error(f'In encypted IP {loc} could not remove depency on instance {inst_rm}')


    if look is not None:
        f_obj.register_with_lookup(look)
    return f_obj


# }}}

# Verilog file parsing {{{
# Pre-process Verilog code to remove comments
def verilog_remove_comments(verilog_code):
    # Remove single-line comments
    code_without_single_comments = re.sub(r'//.*$', '', verilog_code, flags=re.MULTILINE)

    # Remove multi-line comments
    code_without_comments = re.sub(r'/\*.*?\*/', '', code_without_single_comments, flags=re.DOTALL)

    return code_without_comments

def verilog_extract_module_instantiations(verilog_code):
    """
    Extract all module instantiations from Verilog/SystemVerilog code

    Args:
        verilog_code: String containing Verilog/SystemVerilog source code

    Returns:
        List of ModuleInstantiation objects
    """
    VERILOG_KEYWORDS = {
        'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg',
        'always', 'initial', 'begin', 'end', 'if', 'else', 'case', 'endcase',
        'for', 'while', 'repeat', 'forever', 'assign', 'parameter', 'localparam',
        'generate', 'endgenerate', 'genvar', 'function', 'endfunction',
        'task', 'endtask', 'integer', 'real', 'time', 'realtime',
        'supply0', 'supply1', 'tri', 'triand', 'trior', 'trireg', 'uwire',
        'wand', 'wor', 'logic', 'bit', 'byte', 'shortint', 'int', 'longint',
        'shortreal', 'string', 'chandle', 'event', 'packed', 'signed',
        'unsigned', 'struct', 'union', 'enum', 'typedef', 'interface',
        'endinterface', 'modport', 'clocking', 'endclocking', 'property',
        'endproperty', 'sequence', 'endsequence', 'program', 'endprogram',
        'class', 'endclass', 'package', 'endpackage', 'import', 'export',
        'extends', 'implements', 'super', 'this', 'local', 'protected',
        'static', 'automatic', 'rand', 'randc', 'constraint', 'solve',
        'before', 'inside', 'dist', 'covergroup', 'endgroup', 'coverpoint',
        'cross', 'bins', 'binsof', 'illegal_bins', 'ignore_bins', 'wildcard',
        'with', 'matches', 'tagged', 'priority', 'unique', 'unique0',
        'final', 'alias', 'always_comb', 'always_ff', 'always_latch'
    }
    instantiations = []
    instance_name_arr = []

    # Simple tokenization - split by whitespace and common delimiters
    # but keep track of positions for line numbers
    tokens = []
    current_token = ""
    line_num = 1

    for i, char in enumerate(verilog_code):
        if char == '\n':
            if current_token.strip():
                tokens.append((current_token.strip(), line_num))
            current_token = ""
            line_num += 1
        elif char in ' \t\r':
            if current_token.strip():
                tokens.append((current_token.strip(), line_num))
            current_token = ""
        elif char in '();#,=':
            if current_token.strip():
                tokens.append((current_token.strip(), line_num))
            tokens.append((char, line_num))
            current_token = ""
        else:
            current_token += char

    if current_token.strip():
        tokens.append((current_token.strip(), line_num))

    # Parse tokens to find module instantiations
    i = 0
    while i < len(tokens):
        token, _ = tokens[i]

        # Check if this could be a module name (identifier not a keyword)
        if (re.match(r'^[a-zA-Z_]\w*$', token) and
            token.lower() not in VERILOG_KEYWORDS):

            # Look ahead to see if this looks like a module instantiation
            j = i + 1

            # Skip whitespace tokens (shouldn't happen with our tokenizer, but just in case)
            while j < len(tokens) and tokens[j][0] in [' ', '\t', '\n', '\r']:
                j += 1

            if j >= len(tokens):
                break

            # Check for parameter list #(...)
            has_params = False
            if tokens[j][0] == '#':
                has_params = True
                j += 1
                if j < len(tokens) and tokens[j][0] == '(':
                    # Find matching closing paren for parameters
                    paren_count = 1
                    j += 1
                    while j < len(tokens) and paren_count > 0:
                        if tokens[j][0] == '(':
                            paren_count += 1
                        elif tokens[j][0] == ')':
                            paren_count -= 1
                        j += 1

            if j >= len(tokens):
                break

            # Now look for instance name or port list
            instance_name = None

            # Check if next token is an identifier (instance name)
            if (j < len(tokens) and
                re.match(r'^[a-zA-Z_]\w*$', tokens[j][0]) and
                tokens[j][0].lower() not in VERILOG_KEYWORDS):
                instance_name = tokens[j][0]
                j += 1

            # Look for port list starting with '('
            if j < len(tokens) and tokens[j][0] == '(':
                # Find matching closing paren for port list
                paren_count = 1
                port_start = j
                j += 1
                while j < len(tokens) and paren_count > 0:
                    if tokens[j][0] == '(':
                        paren_count += 1
                    elif tokens[j][0] == ')':
                        paren_count -= 1
                    j += 1

                # Look for semicolon after port list
                if j < len(tokens) and tokens[j][0] == ';':
                    # This looks like a valid module instantiation!
                    module_name = token

                    # instantiations.append((module_name, instance_name))
                    if module_name not in instance_name_arr:
                        if instance_name is not None:
                            instance_name_arr.append(instance_name)
                        instantiations.append(module_name)

        i += 1

    return instantiations

# Function to extract include files from Verilog code
def verilog_extract_include_files(verilog_code):
    include_regex = r'`include\s+(["<])([^">]+)[">]'
    matches = re.finditer(include_regex, verilog_code)
    includes = []
    for match in matches:
        inc_is_sys = match.group(1) == '<'
        inc_name = [match.group(2) for match in matches]
        includes.append((inc_name, inc_is_sys))

    return includes


def verilog_extract_module_declarations(verilog_code):
    module_declaration_regex = r'module\s+(\w+)\s*(?:\#\s*\([^)]*\))?\s*\(' #)
    matches = re.finditer(module_declaration_regex, verilog_code)
    declarations = []

    for match in matches:
        module_name = match.group(1)
        declarations.append(module_name)

    return declarations


def parse_verilog_file(look : Optional[Lookup], loc : Path, ver : Optional[str]) -> FileObjVerilog:
    log.info(f"passing Verilog file {loc}:")

    if loc.suffix != '.v' and loc.suffix != '.sv':
        log.warning(f'unexpected verilog extension on {loc} expected .v or .sv')

    # with open(loc, "r", encoding=detect_encoding(loc)) as file:
    #     verilog_code = file.read()
    verilog_code = read_text_file_contents(loc)

    clean_code = verilog_remove_comments(verilog_code)


    f_obj = FileObjVerilog(loc, ver)
    for inc_name, inc_is_sys in verilog_extract_include_files(clean_code):
        vinc = f_obj.VInc(inc_name, inc_is_sys)
        if vinc not in f_obj.verilog_includes:
            log.debug(f'Verilog {loc} includes {inc_name}')
            f_obj.verilog_includes.append(vinc)
    for module_name in verilog_extract_module_declarations(clean_code):
        name = Name(LIB_DEFAULT, module_name)
        if name not in f_obj.entities:
            log.debug(f'Verilog {loc} declards {module_name}')
            f_obj.entities.append(name)
    for module_name in verilog_extract_module_instantiations(clean_code):
        name = Name(LIB_DEFAULT, module_name)
        if name not in f_obj.entity_deps:
            log.debug(f'Verilog {loc} requires {module_name}')
            f_obj.entity_deps.append(name)


    if look is not None:
        f_obj.register_with_lookup(look)
    return f_obj
#}}}

#Parse X_XCI: Xilinx XCI IP File {{{
def parse_x_xci_file_xml(look : Optional[Lookup], loc : Path, xci_f,  ver : Optional[str]) -> Optional[FileObjXXci]:


    log.debug(f"called parse_x_xci_file_xml({loc=})")
    try:
        etree = xml_et.parse(xci_f) #raises xml_et.ParseError
    except xml_et.ParseError as e:
        return None

    ns = {'spirit': 'http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009',
          'xilinx': 'http://www.xilinx.com'
    }

    root = etree.getroot()

    def get_elem_text(xml_tag:str)->str:
        xml_elem = root.find('.//spirit:'+xml_tag, ns)
        assert xml_elem is not None
        assert isinstance(xml_elem.text, str)
        return xml_elem.text.lower()

    def get_elem_text_arr(xml_tag:str)->List[str]:
        xml_elem_arr = root.findall('.//spirit:'+xml_tag, ns)

        text_arr = []
        for xml_elem in xml_elem_arr:
            assert isinstance(xml_elem.text, str)
            text_arr.append(xml_elem.text)
        return text_arr


    xml_lib_arr = get_elem_text_arr('library')
    if(len(xml_lib_arr) != 1 or xml_lib_arr[0] != 'xci'):
        raise RuntimeError("XML Parsing: Expected to find xci under library tag. This may not be an xci file")
    module_name_arr = get_elem_text_arr('instanceName')
    if len(module_name_arr) == 0:
        raise RuntimeError("XML Parsing: could not find .//spirit:instance in xml file")
    if len(module_name_arr) > 1:
        raise RuntimeError("XML Parsing: hdl_depends expect ton only find one .//spirit:instance in xml file")
    module_name = module_name_arr[0]

    name = Name(LIB_DEFAULT, module_name)


    x_dev = None
    x_package = None
    x_speed = None
    x_temp = None
    x_tool_version = None

    for elem in root.findall('.//spirit:configurableElementValue', ns):
        PP = "PROJECT_PARAM."
        RP = "RUNTIME_PARAM."

        id = elem.attrib.get('{'+ns['spirit']+'}referenceId')
        def val() -> str:
            result = elem.text
            if elem.text is None:
                if id == PP+'TEMPERATURE_GRADE':
                    log.warning(f'In Xilinx XCI (xml) {loc} got empty {PP}TEMPERATURE_GRADE assming temperate grade i\n'
                        f'\t(If this is incorect please make a report a bug with the XCI file, correct part number and vivado version)')
                    result = 'i'

            if not isinstance(result, str):
                raise RuntimeError(f'In Xilinx XCI (xml) {loc} for {id=} we got {result=} expected a string')
            assert isinstance(result, str)
            return result
        if id == PP+'DEVICE':
            x_dev = val()
        if id == PP+'PACKAGE':
            x_package = val()
        if id == PP+'SPEEDGRADE':
            x_speed = val()
        if id == PP+'TEMPERATURE_GRADE':
            x_temp = val()
        if id == RP+'SWVERSION':
            x_tool_version = val()

    assert x_dev is not None
    assert x_package is not None
    assert x_speed is not None
    assert x_temp is not None
    assert x_tool_version is not None

    x_device = f"{x_dev}-{x_package}{x_speed}-{x_temp}"
    x_device = x_device.lower()
    log.info(f"Xilinx XCI (xml) {loc} decares {module_name} (tool_verison {x_tool_version}, device {x_device})")

    direct_deps=[]

    #NOTE coef file info is not currently begin extracted

    f_obj = FileObjXXci(loc, ver, x_tool_version, x_device)
    f_obj.entities.append(name)
    f_obj.direct_deps = direct_deps
    if look is not None:
        f_obj.register_with_lookup(look)
    return f_obj

def parse_x_xci_file_json(look : Optional[Lookup], loc : Path, xci_f, ver : Optional[str]) -> Optional[FileObjXXci]:
    try:
        xci_dict = json.load(xci_f) #throws json.decoder.JSONDecodeError
    except json.decoder.JSONDecodeError as e:
        return None

    ip_inst =  xci_dict["ip_inst"]
    module_name = ip_inst["xci_name"]
    name = Name(LIB_DEFAULT, module_name)

    param = ip_inst['parameters']

    prj_param = param['project_parameters']
    def js_val(js):
        assert len(js) == 1
        return js[0]['value']
    x_device = f"{js_val(prj_param['DEVICE'])}-{js_val(prj_param['PACKAGE'])}{js_val(prj_param['SPEEDGRADE'])}-{js_val(prj_param['TEMPERATURE_GRADE'])}"
    x_device = x_device.lower()

    run_param = param['runtime_parameters']
    x_tool_version = js_val(run_param['SWVERSION'])

    log.info(f"Xilinx XCI (json) {loc} decares {module_name} (tool_verison {x_tool_version}, device {x_device})")

    direct_deps = []
    folder = loc.parent
    def append_direct_dep(f_str):
        f_loc = folder/f_str
        direct_deps.append(FileObjDirect(f_loc,ver=ver))


    if 'component_parameters' in param:
        comp_param = param['component_parameters']
        if 'Coefficient_File' in comp_param:
            coe_file = js_val(comp_param['Coefficient_File'])
            log.info(f"Xilinx XCI {loc} has a direct Coefficient_File dependency {coe_file}")
            append_direct_dep(coe_file)
        if 'Coe_File' in comp_param: #This statment has yet to be tested
            coe_file = js_val(comp_param['Coe_File'])
            log.info(f"Xilinx XCI {loc} has a direct Coe_File dependency {coe_file}")
            append_direct_dep(coe_file)

    f_obj = FileObjXXci(loc, ver, x_tool_version, x_device)
    f_obj.entities.append(name)
    f_obj.direct_deps = direct_deps
    if look is not None:
        f_obj.register_with_lookup(look)
    return f_obj

def parse_x_xci_file(look : Optional[Lookup], loc : Path, ver : Optional[str]) -> FileObjXXci:
    log.info(f"parsing Xilinx XCI file {loc}:")
    with open(loc, "rb") as xci_f:
        f_obj = parse_x_xci_file_json(look, loc, xci_f, ver)
        if f_obj is not None:
            return f_obj
        xci_f.seek(0)
        f_obj = parse_x_xci_file_xml(look, loc, xci_f, ver)
        if f_obj is not None:
            return f_obj

    raise RuntimeError(f"Could not parse XCI as XML or JSON, {loc}")


#}}}

#Parse X_BD: Xilinx Block Digarm File {{{
def parse_x_bd_file(look : Optional[Lookup], loc : Path, ver : Optional[str]) -> FileObjXBd:
    log.info(f"parsing Xilinx BD file {loc}:")
    with open(loc, "rb") as json_f:
        bd_dict = json.load(json_f)
    design_dict = bd_dict["design"]
    design_info_dict = design_dict["design_info"]
    module_name = design_info_dict["name"]
    x_tool_version = design_info_dict["tool_version"]
    x_device = design_info_dict["device"]
    log.info(f"Xilinx BD {loc} decares {module_name} (tool_verison {x_tool_version}, device {x_device})")
    f_obj = FileObjXBd(loc, ver, x_tool_version, x_device)
    name = Name(LIB_DEFAULT, module_name)
    f_obj.entities.append(name)

    if 'components' in design_dict:
        for component_name, component in design_dict["components"].items():
            if 'reference_info' in component:
                reference_info = component['reference_info']
                if not 'ref_type' in reference_info:
                    continue
                ref_type = reference_info['ref_type']
                if ref_type != 'hdl':
                    continue
                ref_name = reference_info['ref_name']
                log.debug(f'Xilinx BD {loc} requires {ref_name}')
                name = Name(LIB_DEFAULT, ref_name)
                log.info(f'X_BD {loc} requires HDL instance {component_name} is {ref_name}')
                f_obj.entity_deps.append(name)
                continue
            if 'parameters' in component:
                parameters = component['parameters']
                if not 'ACTIVE_SYNTH_BD' in parameters:
                    continue
                active_synth_bd = parameters['ACTIVE_SYNTH_BD']
                file_name = active_synth_bd['value']
                s = file_name.split('.')
                assert len(s) == 2
                assert s[1] == 'bd'
                ref_name = s[0]
                name = Name(LIB_DEFAULT, ref_name)
                log.info(f'X_BD {loc} requsted BD instance {component_name} is {ref_name}')
                f_obj.entity_deps.append(name)

    if look is not None:
        f_obj.register_with_lookup(look)
    return f_obj



#}}}

 # {{{ class FileLists
@dataclass
class FileLists:
    vhdl    : Optional[List[Tuple[str, Path, str]]] = None
    verilog : Optional[List[Tuple[Path, str]]] = None
    other   : Optional[List[Tuple[Path, str]]] = None
    x_bd    : Optional[List[Tuple[Path, str]]] = None
    x_xci   : Optional[List[Tuple[Path, str]]] = None
    tag_2_ext : Optional[dict[str, List[Path]]] = None
# }}}

class LookupSingular(Lookup): # {{{

    TOML_KEYS_OTHER = [
        "pre_cmds",
        "ignore_libs",
        "ignore_packages",
        "ignore_entities",
        "ignore_components",
    ]
    TOML_KEYS_OPT_VER = [
        "vhdl_files",
        "vhdl_files_file",
        "vhdl_files_glob",
        "vhdl_package_skip_order",
        "verilog_files",
        "verilog_files_file",
        "verilog_files_glob",
        "other_files",
        "other_files_file",
        "other_files_glob",
        "x_bd_files",
        "x_bd_files_file",
        "x_bd_files_glob",
        "x_xci_files",
        "x_xci_files_file",
        "x_xci_files_glob",
        "ext_files",
        "ext_files_file",
        "ext_files_glob",
    ]
    VERSION = HDL_DEPENDS_VERSION_NUM

    def __init__(self, allow_duplicates: bool = True):
        log.debug('LookupSingular::__init__')
        super().__init__()
        self.version = LookupSingular.VERSION
        self.allow_duplicates = allow_duplicates
        self.package_name_2_file_obj: dict[Name, FileObjLookup] = {}
        self.entity_name_2_file_obj: dict[Name, FileObjLookup] = {}
        self.loc_2_file_obj: dict[Path, FileObjLookup] = {}
        self.verilog_file_name_2_file_obj : dict[str, FileObjVerilog] = {}
        self.ignore_set_libs: set[str] = set()
        self.ignore_set_packages: set[Name] = set()
        self.ignore_set_entities: set[Name] = set()
        self.toml_loc: Optional[Path] = None
        self.toml_modification_time: Optional[float]= None
        self.top_lib : Optional[str] = None
        self.ignore_components : set[str] = set()
        self.files_2_skip_from_order : set[Path] = set()
        self.vhdl_file_list = None
        self.verilog_file_list = None
        self.other_file_list = None
        self.x_bd_file_list = None
        self.x_xci_file_list = None
        self.ext_file_list = None
        self.tag_2_ext_file: dict[str, List[Path]] = {}

    def get_tag_2_ext_file(self) -> dict[str, List[Path]]:
        log.debug(f"LookupSingular.get_tag_2_ext_file called -> ret {self.tag_2_ext_file}")
        return self.tag_2_ext_file

    def get_ext_files_for_tag(self, tag:str) -> List[Path]:
        if tag in self.tag_2_ext_file:
            return self.tag_2_ext_file[tag]
        return []

    def _add_to_dict(self, d: dict, key, f_obj: FileObj):
        log.info(f'Adding {key} to dict')
        if key in d:
            if not self.allow_duplicates:
                raise Exception(f"ERROR: tried to add {key} twice")
            item = d[key]
            conflict_obj = None
            if isinstance(item, FileObj):
                conflict_obj = ConflictFileObj( [item, f_obj])
            elif isinstance(item, ConflictFileObj):
                conflict_obj = item
                conflict_obj.add_f_obj(f_obj)
            assert conflict_obj is not None
            d[key] = conflict_obj
        else:
            d[key] = f_obj

    @staticmethod
    def toml_loc_to_pickle_loc(toml_loc: Path) -> Path:
        pickle_loc = toml_loc.with_name('.' + toml_loc.stem + '.pickle')
        return pickle_loc

    @staticmethod
    def atempt_to_load_from_pickle(
            pickle_loc: Path, toml_loc: Path, top_lib : Optional[str]
    ) -> Tuple[Optional[Lookup], FileLists]:
        file_lists = FileLists()

        assert toml_loc.is_file()
        if not pickle_loc.is_file():
            log.debug('will not load from pickle no file at {pickle_loc}')
            return None, file_lists
        log.info(f"atempting to load cache from {pickle_loc}")
        pickle_mod_time = get_file_modification_time(pickle_loc)

        with open(pickle_loc, "rb") as pickle_f:
            inst = pickle.load(pickle_f)

        if LookupSingular.VERSION != inst.version:
            log.info(f'hdldepends version { LookupSingular.VERSION} but pickle top_lib {inst.version} will not load from pickle')
            return None, file_lists

        toml_modification_time = get_file_modification_time(toml_loc)
        if toml_modification_time != inst.toml_modification_time:
            log.info(f"will not load from pickle as {toml_loc} out of date")
            return None, file_lists

        if top_lib != inst.top_lib:
            log.info(f'requested top_lib {top_lib} but pickle top_lib {inst.top_lib} will not load from pickle')
            return None, file_lists

        config = load_config(toml_loc)

        file_lists.vhdl = LookupSingular.get_vhdl_file_list_from_config_dict(
            config, toml_loc.parent, top_lib
        )
        if file_lists.vhdl != inst.vhdl_file_list:
            log.info(f'Will not load from pickle as vhdl_file_list has changed')
            return None, file_lists

        file_lists.verilog = LookupSingular.get_verilog_file_list_from_config_dict(
            config, toml_loc.parent, top_lib
        )
        if file_lists.verilog != inst.verilog_file_list:
            log.info(f'Will not load from pickle as verilog_file_list has changed')
            return None, file_lists

        file_lists.other = LookupSingular.get_other_file_list_from_config_dict(
            config, toml_loc.parent, top_lib=top_lib
        )

        if file_lists.other != inst.other_file_list:
            log.info(f'Will not load from pickle as other_file_list has changed')
            return None, file_lists

        file_lists.x_bd = LookupSingular.get_x_bd_file_list_from_config_dict(
            config, toml_loc.parent, top_lib=top_lib
        )

        if file_lists.x_bd != inst.x_bd_file_list:
            log.info(f'Will not load from pickle as x_bd_file_list has changed')
            return None, file_lists

        file_lists.x_xci = LookupSingular.get_x_xci_file_list_from_config_dict(
            config, toml_loc.parent, top_lib=top_lib
        )

        if file_lists.x_xci != inst.x_xci_file_list:
            log.info(f'Will not load from pickle as x_xci_file_list has changed')
            return None, file_lists

        ext_file_list = LookupSingular.get_ext_file_list_from_config_dict(
            config, toml_loc.parent, top_lib=top_lib
        )
        log.debug(f'New ext_file_list {ext_file_list}')
        file_lists.tag_2_ext = LookupSingular.ext_file_list_2_dict(ext_file_list)


        if file_lists.tag_2_ext != inst.tag_2_ext_file:
            log.info(f'Will not load from pickle as ext_file_list has changed')
            return None, file_lists

        log.info(f"loaded from {pickle_loc}, updating required files")
        any_changes = inst.check_for_src_files_updates()
        if any_changes:
            log.info(f"Updating pickle with the changes detected on disk")
            inst.save_to_pickle(pickle_loc)
        return inst, file_lists

    def save_to_pickle(self, pickle_loc: Path):
        log.info(f"Caching to {pickle_loc}")
        with open(pickle_loc, "wb") as pickle_f:
            pickle.dump(self, pickle_f, protocol=pickle.HIGHEST_PROTOCOL)

    def check_for_src_files_updates(self) -> bool:
        """Returns True if there where any changes"""
        compile_order_out_of_date = False
        any_changes = False
        for _, f_obj_l in self.loc_2_file_obj.items():

            if isinstance(f_obj_l, ConflictFileObj):
                # temp = ','.join([str(cf_obj.loc) for cf_obj in f_obj.get_f_objs()])
                # log.warning("Conflicted file objects: "+temp) #HERE
                # return True
                f_objs = f_obj_l.get_f_objs()
            else:
                f_objs = make_list(f_obj_l)

            for f_obj in f_objs:
                dependency_changes, changes = f_obj.update()

                if dependency_changes:
                    compile_order_out_of_date = True
                if changes:
                    any_changes = True

        if compile_order_out_of_date:
            log.info('Compile order has change')
            # brute force update of dict because resolving a conflict is annoying
            self.package_name_2_file_obj = {}
            self.entity_name_2_file_obj = {}
            for _, f_obj in self.loc_2_file_obj.items():
                assert isinstance(f_obj, FileObj)
                f_obj.register_with_lookup(self, skip_loc=True)

        return any_changes

    @staticmethod
    def _process_config_opt_lib(config: dict, key: str, callback, with_ver : bool, top_lib : Optional[str]):
        if top_lib is None:
            top_lib = LIB_DEFAULT

        ver = None
        def cb(lib, val, ver):
            if with_ver:
                callback(lib, val, ver)
            else:
                assert ver is None
                callback(lib, val)

        for config_key in config.keys():
            if with_ver:
                k, ver = key_split_opt_ver(config_key)
            else:
                k = config_key

            if k != key:
                continue

            c_val = config[config_key]
            if isinstance(c_val, dict):
                for lib, val in c_val.items():
                    if isinstance(val, List):
                        for v in val:
                            cb(lib, v, ver)
                    else:
                        cb(lib, val, ver)
            elif isinstance(c_val, List):
                for v in c_val:
                    cb(top_lib, v, ver)
            else:
                cb(top_lib, c_val, ver)

    @staticmethod
    def extract_set_str_from_config(
        config: dict, key: str
    ) -> Set[str]:
        if key not in config:
            return set()
        val = config[key]
        result = make_set(val)
        log.info(f"{key} = {list(result)}")
        return result

    @staticmethod
    def extract_set_name_from_config(
            config: dict, key: str, top_lib : Optional[str]
    ) -> Set[Name]:
        l = []

        def call_back_func(lib: str, name: str):
            l.append(Name(lib=lib, name=name))

        LookupSingular._process_config_opt_lib(config, key, with_ver=False, callback=call_back_func,top_lib=top_lib)
        log.info(f"{key} = {l}")
        return set(l)

    def initalise_from_config_dict(self, config: dict, work_dir : Path, top_lib : Optional[str], file_lists:Optional[FileLists], add_std_pkg_ignore=True):

        if file_lists is None:
            file_lists = FileLists()

        if 'top_lib' in config:
            self.top_lib = config['top_lib']
        self.ignore_set_libs = LookupSingular.extract_set_str_from_config(
            config, "ignore_libs"
        )
        if add_std_pkg_ignore:
            self.ignore_set_libs.add('ieee')
            self.ignore_set_libs.add('std')

        self.ignore_set_packages = LookupSingular.extract_set_name_from_config(
            config, "ignore_packages", top_lib=top_lib
        )
        self.ignore_set_entities = LookupSingular.extract_set_name_from_config(
            config, "ignore_entities", top_lib=top_lib
        )
        if 'ignore_components' in config:
            self.ignore_components = make_set(config['ignore_components'])

        if file_lists.vhdl is None:
            file_lists.vhdl = LookupSingular.get_vhdl_file_list_from_config_dict(
                config, work_dir, top_lib
            )

        if file_lists.verilog is None:
            file_lists.verilog = LookupSingular.get_verilog_file_list_from_config_dict(
                config, work_dir, top_lib=top_lib
            )

        if file_lists.other is None:
            file_lists.other = LookupSingular.get_other_file_list_from_config_dict(
                config, work_dir, top_lib=top_lib
            )

        if file_lists.x_bd is None:
            file_lists.x_bd = LookupSingular.get_x_bd_file_list_from_config_dict(
                config, work_dir, top_lib=top_lib
            )

        if file_lists.x_xci is None:
            file_lists.x_xci = LookupSingular.get_x_xci_file_list_from_config_dict(
                config, work_dir, top_lib=top_lib
            )

        if file_lists.tag_2_ext is None:
            ext_file_list = LookupSingular.get_ext_file_list_from_config_dict(
                config, work_dir, top_lib=top_lib
            )
            log.debug(f'loaded ext_file_list {ext_file_list}')
            file_lists.tag_2_ext = LookupSingular.ext_file_list_2_dict(ext_file_list)

        def add_file_to_list_skip_order(lib, loc_str):
            loc = path_abs_from_dir(work_dir, Path(loc_str))
            self.files_2_skip_from_order.add(loc)

        LookupSingular._process_config_opt_lib(
            config, "vhdl_package_skip_order", with_ver=False, callback=add_file_to_list_skip_order, top_lib=top_lib
        )

        self.register_file_lists(file_lists)

    def register_file_lists(self, file_lists:FileLists):
        assert file_lists.vhdl is not None
        assert file_lists.verilog is not None
        assert file_lists.other is not None
        assert file_lists.x_bd is not None
        assert file_lists.x_xci is not None
        assert file_lists.tag_2_ext is not None
        self.register_vhdl_file_list(file_lists.vhdl)
        self.register_verilog_file_list(file_lists.verilog)
        self.register_other_file_list(file_lists.other)
        self.register_x_bd_file_list(file_lists.x_bd)
        self.register_x_xci_file_list(file_lists.x_xci)
        self.register_ext_file_list(file_lists.tag_2_ext)

    @staticmethod
    def get_common_file_list_from_config_dict(common_tag : str, config: dict, work_dir: Path, top_lib : Optional[str]) -> List[Tuple[str, Path, str]]:
        common_file_list = []

        def add_file_to_list(lib, loc_str, ver):
            loc = path_abs_from_dir(work_dir, Path(loc_str))
            common_file_list.append((lib, loc, ver))

        LookupSingular._process_config_opt_lib(config, common_tag+"_files", with_ver=True, callback=add_file_to_list, top_lib=top_lib)

        def add_file_list_to_list(lib, f_str,ver):
            fl_loc = Path(f_str)
            fl_loc = path_abs_from_dir(work_dir, fl_loc)
            with open(fl_loc, "r") as f_list_file:
                for loc_str in f_list_file:
                    loc_str = loc_str.strip()
                    loc = path_abs_from_dir(fl_loc.parents[0], Path(loc_str))
                    common_file_list.append((lib, loc, ver))

        LookupSingular._process_config_opt_lib(
            config, common_tag+"_files_file", with_ver=True, callback=add_file_list_to_list, top_lib=top_lib
        )

        glob_dict = {}
        def add_to_glob_str_dict(lib, glob_str, ver):
            if lib not in glob_dict:
                glob_dict[lib] = {}
            if ver not in glob_dict[lib]:
                glob_dict[lib][ver]=[]
            glob_dict[lib][ver].append(glob_str)

        LookupSingular._process_config_opt_lib(
            config, common_tag+"_files_glob", with_ver=True, callback=add_to_glob_str_dict, top_lib=top_lib
        )

        for lib, glob_ver_dict in glob_dict.items():
            for ver, glob_str_list in glob_ver_dict.items():
                loc_rel_list = process_glob_patterns(glob_str_list, work_dir)
                for loc_rel in loc_rel_list:
                    loc = path_abs_from_dir(work_dir, loc_rel)
                    common_file_list.append((lib, loc, ver))

        return common_file_list

    @staticmethod
    def get_common_file_list_from_config_dict_force_default_lib(common_tag : str, config: dict, work_dir: Path, top_lib : Optional[str]):

        common_file_list = LookupSingular.get_common_file_list_from_config_dict(common_tag, config, work_dir, top_lib)

        for lib, loc, ver in common_file_list:
            if lib != LIB_DEFAULT:
                log.error(f'Files types not VHDL must have default library {LIB_DEFAULT} got library {lib} on file {loc} (ver {ver})')

        return [(loc, ver) for _, loc, ver in common_file_list]

    @staticmethod
    def get_vhdl_file_list_from_config_dict(config: dict, work_dir: Path, top_lib : Optional[str]):
        log.debug(f'called get_vhdl_file_list_from_config_dict( top_lib={top_lib} )')
        vhdl_file_list = LookupSingular.get_common_file_list_from_config_dict('vhdl', config, work_dir, top_lib)

        def add_file_to_list_skip_order(lib, loc_str, ver):
            loc = path_abs_from_dir(work_dir, Path(loc_str))
            vhdl_file_list.append((lib, loc, ver))

        LookupSingular._process_config_opt_lib(
            config, "vhdl_package_skip_order", with_ver=True, callback=add_file_to_list_skip_order, top_lib=top_lib
        )

        return vhdl_file_list

    @staticmethod
    def get_verilog_file_list_from_config_dict(config: dict, work_dir: Path, top_lib : Optional[str]):
        log.debug(f'called get_verilog_file_list_from_config_dict( top_lib={top_lib} )')
        return LookupSingular.get_common_file_list_from_config_dict_force_default_lib('verilog', config, work_dir, top_lib)

    @staticmethod
    def get_other_file_list_from_config_dict(config: dict, work_dir: Path, top_lib : Optional[str]):
        return  LookupSingular.get_common_file_list_from_config_dict_force_default_lib('other', config, work_dir, top_lib)

    @staticmethod
    def get_x_bd_file_list_from_config_dict(config: dict, work_dir: Path, top_lib : Optional[str]):
        return  LookupSingular.get_common_file_list_from_config_dict_force_default_lib('x_bd', config, work_dir, top_lib)

    @staticmethod
    def get_x_xci_file_list_from_config_dict(config: dict, work_dir: Path, top_lib : Optional[str]):
        return  LookupSingular.get_common_file_list_from_config_dict_force_default_lib('x_xci', config, work_dir, top_lib)

    @staticmethod
    def get_ext_file_list_from_config_dict(config: dict, work_dir: Path, top_lib : Optional[str]):
        return  LookupSingular.get_common_file_list_from_config_dict_force_default_lib('ext', config, work_dir, top_lib)

    def check_if_skip_from_order(self, loc:Path):
        return loc in self.files_2_skip_from_order

    def register_other_file_list(self, other_file_list : List[Tuple[Path, str]]):
        self.other_file_list = other_file_list
        for loc, ver in other_file_list:

            f_obj = FileObjOther(loc=loc, ver=ver)
            entity_name = Name(LIB_DEFAULT, loc.stem)
            f_obj.entities.append(entity_name)
            self.entity_name_2_file_obj[entity_name] = f_obj
            self.loc_2_file_obj[loc] = f_obj

    def register_x_bd_file_list(self, x_bd_file_list : List[Tuple[Path, str]]):
        self.x_bd_file_list = x_bd_file_list
        for loc, ver in x_bd_file_list:
            parse_x_bd_file(self, loc, ver);

    def register_x_xci_file_list(self, x_xci_file_list : List[Tuple[Path, str]]):
        self.x_xci_file_list = x_xci_file_list
        for loc, ver in x_xci_file_list:
            parse_x_xci_file(self, loc, ver);

    def register_vhdl_file_list(self, vhdl_file_list : List[Tuple[str, Path, str]]):
        self.vhdl_file_list = vhdl_file_list
        for lib, loc, ver in vhdl_file_list:
            parse_vhdl_file(self, loc, lib=lib, ver=ver)

    def register_verilog_file_list(self, verilog_file_list : List[Tuple[Path, str]]):
        self.verilog_file_list = verilog_file_list
        for loc, ver in verilog_file_list:
            parse_verilog_file(self, loc, ver=ver)

    @staticmethod
    def ext_file_list_2_dict(ext_file_list : List[Tuple[Path, str]]) -> dict[str, List[Path]]:
        tag_2_ext_file = {}
        for loc, ver in ext_file_list:
            if ver not in tag_2_ext_file:
                tag_2_ext_file[ver] = []
            tag_2_ext_file[ver].append(loc)
        return tag_2_ext_file

    def register_ext_file_list(self, tag_2_ext_file : dict[str, List[Path]]):
        self.tag_2_ext_file = tag_2_ext_file

    @staticmethod
    def create_from_config_dict(config: dict, work_dir: Path, **kwargs):

        inst = LookupSingular()
        inst.initalise_from_config_dict(config, work_dir, **kwargs)
        return inst


    def add_vhdl_package(self, name: Name, f_obj: FileObjVhdl):
        self._add_to_dict(self.package_name_2_file_obj, name, f_obj)

    def add_entity(self, name: Name, f_obj: FileObj):
        self._add_to_dict(self.entity_name_2_file_obj, name, f_obj)

    def add_loc(self, loc: Path, f_obj: FileObj):
        loc = resolve_abs_path(loc)
        self._add_to_dict(self.loc_2_file_obj, loc, f_obj)

    def add_verilog_file_name(self, file_name: str, f_obj : FileObjVerilog):
        self._add_to_dict(self.verilog_file_name_2_file_obj, file_name, f_obj)

    def get_loc(self, loc: Path):
        loc = resolve_abs_path(loc)
        return self.loc_2_file_obj[loc]

    def has_loc(self, loc: Path):
        loc = resolve_abs_path(loc)
        return loc in self.loc_2_file_obj

    def get_vhdl_package(self, name: Name, f_obj_required_by : Optional[FileObjVhdl]) -> Optional[FileObjVhdl]:
        loc_str = 'None'
        if f_obj_required_by is not None:
            loc_str = str(f_obj_required_by.loc)
        if name not in self.package_name_2_file_obj:
            if name.lib in self.ignore_set_libs:
                return None
            if name in self.ignore_set_packages:
                return None
            raise KeyError(f"ERROR: Could not find package {name} required by {loc_str}")

        item = self.package_name_2_file_obj[name]
        if isinstance(item, FileObj):
            assert isinstance(item,FileObjVhdl)
            return item
        elif isinstance(item, ConflictFileObj):
            item.log_confict(name)
            raise KeyError(f"ERROR: confict on package {name} required by {loc_str}")

    def get_entity(self, name: Name, f_obj_required_by : Optional[FileObj]) -> Optional[FileObj]:
        loc_str = 'None'
        if f_obj_required_by is not None:
            loc_str = str(f_obj_required_by.loc)
        if name not in self.entity_name_2_file_obj:
            if name.lib in self.ignore_set_libs:
                return None

            if name in self.ignore_set_entities:
                return None
            raise KeyError(f"ERROR: Could not find entity {name} required by {loc_str}")

        item = self.entity_name_2_file_obj[name]
        if isinstance(item, FileObj):
            return item
        elif isinstance(item, ConflictFileObj):
            resolved = item.resolve_conflict(x_tool_version=self.x_tool_version, x_device=self.x_device)
            if isinstance(resolved, FileObj):
                return resolved
            item.log_confict(name)
            raise KeyError(f"ERROR: confict on entity {name} required by {loc_str}")

    def get_top_lib(self):
        return self.top_lib

    def set_top_lib(self, top_lib : Optional[str] = None):
        self.top_lib = top_lib

    def get_file_list(self, lib:Optional[str]=None):
        file_list = []
        for f_obj in self.loc_2_file_obj.values():
            assert not isinstance(f_obj, ConflictFileObj)
            if f_obj.loc in self.files_2_skip_from_order:
                continue #skip
            if lib is None or lib == f_obj.lib:
                file_list.append(f_obj)
        return file_list

    def write_file_list(self, f_loc, f_type : Optional[FileObjType]=None, lib : Optional[str] = None):
        file_list = self.get_file_list(lib=lib)
        with open(f_loc, 'w') as f:
            for f_obj in file_list:
                if f_type is not None:
                    if f_obj.f_type != f_type:
                        continue
                if lib is None:
                    f.write(f'{f_obj.lib}\t{f_obj.loc}\n')
                else:
                    f.write(str(f_obj.loc)+'\n')

    def write_ext_file_list(self, f_loc : Path, ver_tag : Optional[str] = None):
        log.debug(f'Called write_ext_file_list(f_loc = {f_loc}, ver_tag = {ver_tag})')
        log.debug(f'self {self}')
        with open(f_loc, 'w') as f:
            if ver_tag is None:
                tag_2_ext = self.get_tag_2_ext_file()
                for ver_tag, ext_l in tag_2_ext.items():
                    for ext in ext_l:
                        f.write(f'{ver_tag}\t{ext}\n')
            else:
                ext_l = self.get_ext_files_for_tag(ver_tag)
                for ext in ext_l:
                    f.write(f'{ext}\n')


#}}}

class LookupMulti(LookupSingular):  # {{{
    TOML_KEYS_OTHER = ["sub"]
    TOML_KEYS_OPT_VER = []

    def __init__(
            self, look_subs: List[LookupSingular]): #, file_list: List[Tuple[str, Path]] = [] ):
        log.debug('LookupMulti::__init__')
        self.look_subs = look_subs
        super().__init__(allow_duplicates=True)
        self.f_obj_top = None
        self._compile_order = None

    def set_x_tool_version(self, x_tool_version : str):
        for sub in self.look_subs:
            sub.set_x_tool_version(x_tool_version)
        Lookup.set_x_tool_version(self, x_tool_version)

    def set_x_device(self, x_device : str):
        log.debug(f'LookupMulti::set_x_device({x_device})')
        for sub in self.look_subs:
            sub.set_x_device(x_device)
        Lookup.set_x_device(self, x_device)

    def get_tag_2_ext_file(self) -> dict[str, List[Path]]:
        log.debug("LookupMulti.get_tag_2_ext_file called")
        tag_2_ext = LookupSingular.get_tag_2_ext_file(self).copy()
        for sub in self.look_subs:
            for tag, f_l in sub.get_tag_2_ext_file().items():
                if tag in tag_2_ext:
                    tag_2_ext[tag].extend(f_l)
                else:
                    tag_2_ext[tag] = f_l
        return tag_2_ext

    def get_ext_files_for_tag(self, tag:str) -> List[Path]:
        f_l = LookupSingular.get_ext_files_for_tag(self,tag)
        for sub in self.look_subs:
            f_l.extend( LookupSingular.get_ext_files_for_tag(sub,tag))
        return f_l

    @staticmethod
    def create_from_config_dict(
            config: dict, work_dir: Path, look_subs=[], **kwargs
    ):

        look = LookupMulti(look_subs)
        look.initalise_from_config_dict(config, work_dir, **kwargs)
        return look

    def register_vhdl_file_list(self, vhdl_file_list:List[Tuple[str,Path,str]]):
        self.vhdl_file_list = vhdl_file_list
        for lib, loc, ver in vhdl_file_list:
            f_obj = self._get_loc_from_common(loc)
            if f_obj is not None:
                if f_obj.lib != lib:
                    raise RuntimeError(f'Double library error {f_obj.lib} != {lib}. Check if file has been added twice with different libraries')
                if f_obj.ver != ver:
                    raise RuntimeError(f'Double version error {f_obj.ver} != {ver}. Check if file has been added twice with different versions')
                f_obj.register_with_lookup(self)
            else:
                # not passed in common lookup pass in prj lookup
                f_obj = parse_vhdl_file(self, loc, lib=lib, ver=ver)

    def register_verilog_file_list(self, verilog_file_list:List):
        log.debug(f'register_verilog_file_list({verilog_file_list=}) called')
        self.verilog_file_list = verilog_file_list
        for loc, ver in verilog_file_list:
            f_obj = self._get_loc_from_common(loc)
            if f_obj is not None:
                f_obj.register_with_lookup(self)
                assert(f_obj.ver == ver)
            else:
                f_obj = parse_verilog_file(self, loc, ver)



    def get_loc(self, loc: Path, type_to_add_to_if_not_found : Optional[FileObjType]=None, lib_to_add_to_if_not_found: str = LIB_DEFAULT, ver_to_add_to_if_not_found=None):
    # def get_loc(self, loc: Path, lib_to_add_to_if_not_found: Optional[str] = None):
        try:
            return super().get_loc(loc)
        except KeyError:
            f_obj = self._get_loc_from_common(loc)
            if f_obj is None:

                if type_to_add_to_if_not_found is None:
                    match loc.suffix:
                        case ".vhd" | ".vhdl":
                            type_to_add_to_if_not_found = FileObjType.VHDL
                        case ".v":
                            type_to_add_to_if_not_found = FileObjType.VERILOG
                        case ".bd":
                            type_to_add_to_if_not_found = FileObjType.X_BD
                        case ".xci":
                            type_to_add_to_if_not_found = FileObjType.X_XCI
                        case _:
                            pass

                if type_to_add_to_if_not_found is not None:
                    ver = ver_to_add_to_if_not_found
                    if type_to_add_to_if_not_found is FileObjType.VHDL:
                        f_obj = parse_vhdl_file( self, loc, lib=lib_to_add_to_if_not_found, ver=ver)
                    elif type_to_add_to_if_not_found is FileObjType.VERILOG:
                        f_obj = parse_verilog_file(self, loc, ver)
                    elif type_to_add_to_if_not_found is FileObjType.X_BD:
                        f_obj = parse_x_bd_file(self, loc, ver)
                    elif type_to_add_to_if_not_found is FileObjType.X_XCI:
                        f_obj = parse_x_xci_file(self, loc, ver)
                    else:
                        raise TypeError(f'Unexpected top level file type:{type_to_add_to_if_not_found}')
                else:
                    raise KeyError(f"file {loc} not found in dependency lookups")
            return f_obj


    def _get_loc_from_common(self, loc: Path) -> Optional[FileObj]:
        for l_common in self.look_subs:
            if l_common.has_loc(loc):
                f_obj = l_common.get_loc(loc)
                assert isinstance(f_obj, FileObj)
        return None

    def check_if_skip_from_order(self, loc:Path):
        if LookupSingular.check_if_skip_from_order(self,loc):
            return True
        for l_common in self.look_subs:
            if l_common.check_if_skip_from_order(loc):
                return True
        return False

    def get_top_lib(self) -> Optional[str]:
        if super().get_top_lib() is not None:
            return super().get_top_lib()
        for l_common in self.look_subs:
            top_lib = l_common.get_top_lib()
            if top_lib is not None:
                return top_lib
        return None

    def _get_named_item(
        self, item_ref: str, name: Name, call_back_func_arr, f_obj_required_by : Optional[FileObj]
    ) -> Optional[FileObj]:
        for call_back in call_back_func_arr:
            try:
                result = call_back(name, f_obj_required_by)
                return result
            except KeyError:
                pass


        loc_str = 'None'
        if f_obj_required_by is not None:
            loc_str = f'{f_obj_required_by.lib}:{f_obj_required_by.loc}'
        raise KeyError(f"{item_ref} {name} not found in depndency lookups. required by file {loc_str}")

    def get_vhdl_package(self, name: Name, f_obj_required_by : Optional[FileObjVhdl]) -> Optional[FileObjVhdl]:
        def cb(name: Name, f_obj_required_by : Optional[FileObj]):
            assert f_obj_required_by is None or isinstance(f_obj_required_by, FileObjVhdl)
            return LookupSingular.get_vhdl_package(self, name, f_obj_required_by)

        call_back_func_arr = [cb] + [l.get_vhdl_package for l in self.look_subs]
        f_obj = self._get_named_item("package", name, call_back_func_arr, f_obj_required_by)
        assert f_obj is None or isinstance(f_obj, FileObjVhdl)
        return f_obj

    def get_entity(self, name: Name, f_obj_required_by : Optional[FileObj]) -> Optional[FileObj]:
        def cb(name: Name, f_obj_required_by : Optional[FileObj]):
            return LookupSingular.get_entity(self, name, f_obj_required_by)

        call_back_func_arr = [cb] + [l.get_entity for l in self.look_subs]
        return self._get_named_item("entity", name, call_back_func_arr, f_obj_required_by)

    def get_file_list(self, lib:Optional[str]=None):
        file_list = LookupSingular.get_file_list(self, lib=lib)

        for s in self.look_subs:
            file_list += s.get_file_list(lib=lib)
        return file_list
#}}}

class LookupPrj(LookupMulti): #{{{
    TOML_KEYS_OTHER = ["top_entity", "x_tool_version", "x_device"]
    TOML_KEYS_OPT_VER = ["top_vhdl_file", "top_verilog_file", "top_x_bd_file"]

    def __init__(
            self, look_subs: List[LookupSingular]) : #, file_list: List[Tuple[str, Path]] = [] ):
        log.debug('LookupPrj::__init__')
        super().__init__(look_subs)
        self.f_obj_top = None
        self._compile_order = None

    def set_top_lib(self, top_lib : Optional[str] = None):
        self._compile_order = None
        super().set_top_lib(top_lib)

    @staticmethod
    def create_from_config_dict(
            config: dict, work_dir: Path, look_subs=[], top_lib=None, **kwargs
    ):

        look = LookupPrj(look_subs)
        look.initalise_from_config_dict(config, work_dir, top_lib=top_lib, **kwargs)
        sum = 0
        if "top_vhdl_file" in config:
            sum += 1
        if "top_verilog_file" in config:
            sum += 1
        if "top_x_bd_file" in config:
            sum += 1
        if sum > 1:
            raise RuntimeError("Only top_vhdl_file or top_verilog_file or top_x_bd_file is supported")


        config_keys = config.keys()
        # assert isinstance(config_keys, List)
        # assert all(isinstance(item, str) for item in config_keys)
        config_keys = keys_rm_opt_ver(config_keys)
        if "top_vhdl_file" in config_keys:

            l = []

            def callback(lib: str, loc_str: str, ver:str):
                loc = work_dir / loc_str
                n = (lib, loc, ver)
                if len(l) != 0:
                    raise Exception(f"only supports one top_vhdl_file got {l[0]} and {n}")
                l.append(n)

            LookupSingular._process_config_opt_lib(config, "top_vhdl_file", with_ver=True, callback=callback, top_lib=top_lib)

            assert len(l) == 1

            lib = l[0][0]
            loc = Path(l[0][1])
            ver = l[0][2] #TODO

            look.set_top_file(loc, FileObjType.VHDL, lib, ver)

        if "top_verilog_file" in config_keys:

            l = []

            def callback(lib: str, loc_str: str, ver : str):
                loc = work_dir / loc_str
                n = (lib, loc, ver)
                if len(l) != 0:
                    raise Exception(f"only supports one top_verilog_file got {l[0]} and {n}")
                l.append(n)

            LookupSingular._process_config_opt_lib(config, "top_verilog_file", with_ver=True, callback=callback, top_lib=top_lib)

            assert len(l) == 1

            lib = l[0][0]
            loc = Path(l[0][1])
            ver = l[0][2] #TODO
            if lib != LIB_DEFAULT:
                log.error(f'verilog does not support libraries got lib {lib}')
            look.set_top_file(loc, FileObjType.VERILOG, ver)

        if "top_x_bd_file" in config_keys:

            l = []

            def callback(lib: str, loc_str: str, ver):
                loc = work_dir / loc_str
                n = (lib, loc, ver)
                if len(l) != 0:
                    raise Exception(f"only supports one top_x_bd_file got {l[0]} and {n}")
                l.append(n)

            LookupSingular._process_config_opt_lib(config, "top_x_bd_file", with_ver=True, callback=callback, top_lib=top_lib)

            assert len(l) == 1

            lib = l[0][0]
            loc = Path(l[0][1])
            ver = l[0][2] #TODO
            if lib != LIB_DEFAULT:
                log.error(f'x_bd does not support libraries got lib {lib}')
            look.set_top_file(loc, FileObjType.X_BD, ver)

        if "top_entity" in config:
            name_list = []
            def callback(lib: str, name_str: str):
                name = Name(lib, name_str)
                if len(name_list) != 0:
                    raise Exception(f"only supports one entity but got {name_list[0]} and {name}")
                name_list.append(name)

            LookupSingular._process_config_opt_lib(config, "top_entity", with_ver=False, callback=callback, top_lib=top_lib)
            assert len(name_list) == 1
            name = name_list[0]
            look.set_top_entity(name, do_not_replace_top_file=True)

        if "x_tool_version" in config:
            x_tool_version = config['x_tool_version']
            if not isinstance(x_tool_version,str):
                raise RuntimeError(f"x_tool_version needs to be a string got {x_tool_version}")
            look.set_x_tool_version(x_tool_version)

        if "x_device" in config:
            x_device = config['x_device']
            if not isinstance(x_device,str):
                raise RuntimeError(f"x_device needs to be a string got {x_device}")
            look.set_x_device(x_device)

        return look

    def set_top_file(self, loc: Path, f_type : Optional[FileObjType]=None, lib:str=LIB_DEFAULT, ver:Optional[str]=None):
        log.info(f'setting {loc} with type {f_type} as top')
        self.f_obj_top = self.get_loc(loc, type_to_add_to_if_not_found=f_type, lib_to_add_to_if_not_found=lib, ver_to_add_to_if_not_found=ver)
        self._compile_order = None

    def set_top_entity(self, name, do_not_replace_top_file=True):
        if do_not_replace_top_file and self.f_obj_top is not None:
            f_obj = self.get_entity(name, f_obj_required_by=None)
            if f_obj != self.f_obj_top:
                assert isinstance(self.f_obj_top, FileObj)
                raise RuntimeError(f'top entity specifed {name} but top file specifed {self.f_obj_top.loc}')

        else:
            f_obj = self.get_entity(name, f_obj_required_by=None)
            assert f_obj is not None
            if isinstance(f_obj, FileObjVhdl):
                log.info(f'top_entity {name} found in vhdl file {f_obj.loc}')
                self.set_top_file(f_obj.loc, lib=f_obj.lib, ver=f_obj.ver)
            else:
                log.info(f'top_entity {name} found in file {f_obj.loc}')
                self.set_top_file(f_obj.loc, ver=f_obj.ver)

    def has_top_file(self) -> bool:
        return self.f_obj_top is not None

    @property
    def compile_order(self):
        if self._compile_order is None:
            if self.f_obj_top is None:
                raise Exception(
                    "top_file must be declared in config or on command line"
                )

            assert isinstance(self.f_obj_top, FileObj)
            self._compile_order = self.f_obj_top.get_compile_order(self)
        return self._compile_order

    def print_compile_order(self):
        print("compile order:")
        for f_obj in self.compile_order:
            assert isinstance(f_obj.level, int)
            print(f'  {f_obj.file_type_str_w_ver_tag+":":10} {"|---"*f_obj.level}{f_obj.lib}: {f_obj.loc}')

    def write_compile_order(self, compile_order_loc: Path, f_type : Optional[FileObjType]=None):
        with open(compile_order_loc, "w") as f_order:
            for f_obj in self.compile_order:
                if f_type is not None:
                    if f_obj.f_type != f_type:
                        continue
                    f_order.write(f"{f_obj.lib} {f_obj.loc}\n")
                else:
                    f_order.write(f"{f_obj.file_type_str_w_ver_tag} {f_obj.lib} {f_obj.loc}\n")


    def write_compile_order_lib(self, compile_order_loc: Path, lib:Optional[str], f_type: Optional[FileObjType]=None):
        log.debug(f'write_compile_order_lib({compile_order_loc=}, {lib=}, {f_type=}')
        lines = 0
        with open(compile_order_loc, "w") as f_order:
            for f_obj in self.compile_order:
                if f_type is not None:
                    if f_obj.f_type != f_type:
                        continue
                if (lib is None) or (f_obj.lib is None and lib == LIB_DEFAULT) or (f_obj.lib == lib):
                    f_order.write(f"{f_obj.loc}\n")
                    lines += 1
        if lines == 0:
            log.warning(f'not files found for libarary {lib}')

    def write_compile_order_json(self, output_loc: Path):
        """Write complete project compile order to JSON file including both compile order and external files.
        Args:
            output_loc: Path to the output JSON file
        """
        files_list = []

        # Add external files first (same logic as write_ext_file_list)
        tag_2_ext = self.get_tag_2_ext_file()
        for ver_tag, ext_l in tag_2_ext.items():
            for ext_file in ext_l:
                # Determine file type from extension
                file_ext = Path(ext_file).suffix.upper().lstrip('.')
                if not file_ext:
                    file_ext = "UNKNOWN"

                ext_file_entry = {
                    "type": "EXTERNAL",
                    "file_ext": file_ext,
                    "path": str(ext_file)
                }
            if ver_tag is not None:
                ext_file_entry["ver_tag"] = ver_tag
                files_list.append(ext_file_entry)

        # Add compile order files (same logic as write_compile_order)
        for f_obj in self.compile_order:
            file_entry = {
                "type": f_obj.file_type_str,
                "path": str(f_obj.loc)
            }
            if f_obj is self.f_obj_top:
                file_entry["is_top"] = True
            if f_obj.lib is not None:
                file_entry["library"] = f_obj.lib
            if f_obj.ver_tag is not None:
                ext_file_entry["ver_tag"] = f_obj.ver_tag
            files_list.append(file_entry)

        # Create the final JSON structure
        project_compile_order_json = {
            "files": files_list
        }

        # Write to JSON file
        with open(output_loc, "w") as f:
            json.dump(project_compile_order_json, f, indent=2)
#}}}

# Handling of configuration files {{{
def load_config(toml_loc):
    is_json = toml_loc.suffix == '.json'
    is_toml = toml_loc.suffix == '.toml' and tomllib is not None
    is_yaml = toml_loc.suffix == '.yaml' and yaml is not None
    if (sum([is_json, is_toml, is_yaml]) != 1) :
        raise RuntimeError("Unexpected file format "+toml_loc.suffix)

    try:
        with open(toml_loc, "rb") as toml_f:
            if is_json:
                return json.load(toml_f)
            if is_toml:
                return tomllib.load(toml_f)
            if is_yaml:
                return yaml.safe_load(toml_f)
    except Exception as e:
        print(f'ERROR on file {toml_loc}')
        raise e

def create_lookup_from_toml(
    toml_loc: Path, work_dir: Optional[Path] = None, attemp_read_pickle = True, write_pickle = True, force_LookupPrj=False, top_lib : Optional[str]= None
):
    log.debug(f'config loc {toml_loc} , work_dir {work_dir}, attemp_read_pickle {attemp_read_pickle}, write_pickle {write_pickle}, force_LookupPrj {force_LookupPrj}, top_lib {top_lib}')

    is_json = toml_loc.suffix == '.json'

    if not is_json and toml_loc.suffix != '.toml':
        if len(toml_loc.suffix) == 0:
            log.info('f adding .toml suffix/extension to {toml_loc}')
            toml_loc = toml_loc.with_suffix('.toml')
        else:
            raise Exception(f'{toml_loc} expected suffix .toml or .json but got {toml_loc.suffix}')

    if not toml_loc.is_file():
        if toml_loc.is_absolute() or work_dir is None:
            raise FileNotFoundError(f"ERROR could not find file {toml_loc}")
        log.info(f"tring to find {toml_loc} in previouse directoires")
        temp_dir = resolve_abs_path(work_dir)
        test = temp_dir / toml_loc
        while not test.is_file():
            try:
                temp_dir = temp_dir.parents[0]
            except IndexError:
                raise FileNotFoundError(f"ERROR could not find file {toml_loc}")
            test = temp_dir / toml_loc
        toml_loc = test


    pickle_loc = LookupSingular.toml_loc_to_pickle_loc(toml_loc)
    config = load_config(toml_loc)

    work_dir = toml_loc.parents[0]

    look_subs = []
    if "sub" in config:
        c_locs = config["sub"]
        c_locs = make_list(c_locs)
        for loc in c_locs:
            loc = Path(loc)
            look_subs.append(
                create_lookup_from_toml(loc, work_dir, attemp_read_pickle=attemp_read_pickle, write_pickle=write_pickle, top_lib=top_lib)
            )

    if 'pre_cmds' in config:
        for cmd in make_list(config['pre_cmds']):
            log.info(f'Running {cmd=}')
            subprocess.check_output(cmd, shell=True, cwd=work_dir)

    file_lists = FileLists()
    # vhdl_file_list = None
    # verilog_file_list = None
    # other_file_list = None
    # x_bd_file_list = None
    # x_xci_file_list = None
    # ext_file_list = None
    if attemp_read_pickle:
        # inst, vhdl_file_list, verilog_file_list, other_file_list, x_bd_file_list, x_xci_file_list = LookupSingular.atempt_to_load_from_pickle(pickle_loc, toml_loc, top_lib=top_lib)
        inst, file_lists = LookupSingular.atempt_to_load_from_pickle(pickle_loc, toml_loc, top_lib=top_lib)
        if inst is not None:
            if hasattr(inst, 'look_subs'):
                assert isinstance(inst, LookupMulti)
                inst.look_subs = look_subs
            elif len(look_subs) != 0:
                log.warning(f"Config {toml_loc} has look_subs but pickle doesn't will not load from pickle")
                inst = None
        if inst is not None:
            return inst
        # if file_lists.vhdl is not None:
        #     vhdl_file_list = file_lists.vhdl
        # if file_lists.verilog is not None:
        #     verilog_file_list = file_lists.verilog
        # if file_lists.other is not None:
        #     other_file_list = file_lists.other
        # if file_lists.x_bd is not None:
        #     x_bd_file_list = file_lists.x_bd
        # if file_lists.x_xci is not None:
        #     x_xci_file_list = file_lists.x_xci
        # if file_lists.ext is not None:
        #     ext_file_list = file_lists.ext

    # picke_loc = LookupSingular.toml_loc_to_pickle_loc(toml_loc)
    config_keys = config.keys()
    #TODO workout how to typecheck dict_keyes type
    # print(f'config_keys.type {type(config_keys)}')
    # assert isinstance(config_keys, Set)
    # assert all(isinstance(item, str) for item in config_keys)
    config_keys = keys_rm_opt_ver(config_keys)
    error_key = issue_key(LookupPrj.TOML_KEYS_OTHER + LookupMulti.TOML_KEYS_OTHER + LookupSingular.TOML_KEYS_OTHER + LookupPrj.TOML_KEYS_OPT_VER + LookupMulti.TOML_KEYS_OPT_VER + LookupSingular.TOML_KEYS_OPT_VER, config_keys)
    if error_key is not None:
        raise KeyError(f"Got unexpected key {error_key} in file {toml_loc}")

    #TODO check that TOML_KEYS_OTHER do not contain TOML_KEY_VER_SEP!!!
    if force_LookupPrj or contains_any(config_keys, LookupPrj.TOML_KEYS_OTHER + LookupPrj.TOML_KEYS_OPT_VER):

        log.info(f"create LookupPrj from {toml_loc}")
        inst = LookupPrj.create_from_config_dict(
            config, work_dir=work_dir, look_subs=look_subs, top_lib=top_lib, file_lists=file_lists
        )


    elif contains_any(config_keys, LookupMulti.TOML_KEYS_OTHER + LookupMulti.TOML_KEYS_OPT_VER):

        log.info(f"create LookupMulti from {toml_loc}")
        inst = LookupMulti.create_from_config_dict(
            config, work_dir=work_dir, look_subs=look_subs, top_lib=top_lib, file_lists=file_lists
        )

    else :
        inst = LookupSingular.create_from_config_dict(
            config, work_dir=work_dir, top_lib=top_lib, file_lists=file_lists
        )

    print(f'toml_loc {toml_loc}')
    time = get_file_modification_time(toml_loc)
    assert(time is not None)
    inst.toml_modification_time = time

    if write_pickle:
        look_subs = None
        if hasattr(inst, 'look_subs'):
            assert isinstance(inst, LookupMulti) or isinstance(inst, LookupPrj)
            look_subs = inst.look_subs
        inst.save_to_pickle(pickle_loc)
        if look_subs is not None:
            assert isinstance(inst, LookupMulti) or isinstance(inst, LookupPrj)
            inst.look_subs = look_subs
    return inst
# }}}

# {{{ Main method handling
def extract_tuple_str(s)-> Tuple[str, str]:
    try:
        lib, f = s.split(':')
        return lib, f
    except:
        raise argparse.ArgumentTypeError("--compile-order-lib expects tuples of lib:path")

def set_log_level_from_verbose(args):
    global log_level
    if args.verbose is not None:
        log_level = args.verbose

def hdldepends():
    parser = argparse.ArgumentParser(description="HDL dependency parser")

    parser.add_argument(
        "-v", "--verbose", action="count", help="Verbose level, repeat up to two times"
    )
    parser.add_argument("-c", "--clear-pickle", action="store_true", help="Delete pickle cache files first.")
    parser.add_argument("--no-pickle", action="store_true", help="Do not write or read any pickle caches")
    parser.add_argument(
        "config_file",
        nargs="+",  # Allows one or more files
        type=str,
        help="Paths to / File Names of, the config TOML input file(s).",
    )
    parser.add_argument("--top-file", type=str, help="Location to top level file (expects file to already be added)")
    parser.add_argument("--top-file-type", type=extract_tuple_str, help="Expects '<type>:<file>' Location to top level file (will add the file if not already added")
    parser.add_argument("--top-entity", type=str, help="Top level entity to use (expects entity to already be added)")
    parser.add_argument("--top-vhdl-lib", type=str, help="Top level VHDL library")
    parser.add_argument(
        "--compile-order", type=str, help="Path to the compile order output file. Each line of the file contains library and paths"
    )
    parser.add_argument(
        "--compile-order-path-only", type=str, help="Path to the compile order output file. File contains Paths only"
    )
    parser.add_argument(
        "--compile-order-type", nargs ="+", type=extract_tuple_str, help="Expects '<type>:<file>' Write compile order of passed  <type> to <file>."
    )
    parser.add_argument(
        "--compile-order-vhdl-lib", nargs ="+", type=extract_tuple_str, help="Expects '<lib>:<file>' where 'file' is location to write the VHDL compile order of libary 'lib'."
    )
    parser.add_argument(
        "--file-list", type=str, help="Output full file list of in project"
    )
    parser.add_argument(
        "--file-list-type", nargs="+", type=extract_tuple_str, help="Output full VHDL file list of in project"
    )
    parser.add_argument(
        "--file-list-vhdl-lib", nargs="+", type=extract_tuple_str, help="Expects '<lib>:<file>' where <file> is location to write the file list of VHDL library <lib>."
    )
    parser.add_argument(
        "--ext-file-list", type=str, help="external file list"
    )
    parser.add_argument(
        "--ext-file-list-tag", nargs="+", type=extract_tuple_str, help="external file list for a given tag, Expects '<tag>:<file>'"
    )
    parser.add_argument(
        "--compile-order-json", type=str,
        help="Create a complete project compile order JSON file including both compile order and external files"
    )
    parser.add_argument( "--x-tool-version", type=str, help="Xilinx tool version (used for choosing x_bd and x_xci files)")
    parser.add_argument( "--x-device", type=str, help="Xilinx device (used for choosing x_bd and x_xci files)")
    args = parser.parse_args()

    set_log_level_from_verbose(args)


    work_dir=Path('.')
    top_lib = None
    if args.top_vhdl_lib:
        top_lib = args.top_vhdl_lib

    attemp_read_pickle = not args.clear_pickle and not args.no_pickle
    write_pickle = not args.no_pickle
    look = None
    if args.config_file:
        if len(args.config_file) == 1:
            log.debug('creating top level project toml')
            look = create_lookup_from_toml(Path(args.config_file[0]), work_dir=work_dir,
                force_LookupPrj=True, attemp_read_pickle=attemp_read_pickle, write_pickle=write_pickle, top_lib=top_lib
            )
            assert isinstance(look, LookupPrj)
            # look.x_tool_version = x_tool_version
            # look.x_device = x_device
        else:
            look_subs = []
            for c_toml in look_subs:
                look_subs.append(
                    create_lookup_from_toml(
                        Path(c_toml), work_dir=work_dir, attemp_read_pickle=attemp_read_pickle, write_pickle=write_pickle, top_lib=top_lib
                    )
                )
            look = LookupPrj(look_subs)
            # look.x_tool_version = x_tool_version
            # look.x_device = x_device

    assert look is not None

    x_tool_version = args.x_tool_version
    if x_tool_version is not None:
        look.set_x_tool_version(x_tool_version)

    x_device = args.x_device
    if x_device is not None:
        look.set_x_device(x_device)


    if args.top_file_type:
        f_type_str, file_str = args.file_file_type
        f_type = string_to_FileObjType(f_type_str)
        f_loc = Path(file_str)
        assert isinstance(look, LookupPrj)
        look.set_top_file(f_loc, f_type=f_type)

    if args.top_file:
        assert isinstance(look, LookupPrj)
        look.set_top_file(Path(args.top_file))


    if args.top_entity:
        assert isinstance(look, LookupPrj)
        lib = top_lib
        if lib is None:
            lib = LIB_DEFAULT
        name = Name(lib, args.top_entity)
        look.set_top_entity(name, do_not_replace_top_file=True)

    if look.has_top_file():
        assert isinstance(look, LookupPrj)
        look.print_compile_order()

    if args.file_list is not None:
        look.write_file_list(Path(args.file_list))

    if args.file_list_type is not None:
        for f_type_str, file_out_str in args.file_list_type:
            f_type = string_to_FileObjType(f_type_str)
            look.write_file_list(Path(file_out_str), f_type)

    if args.file_list_vhdl_lib is not None:
        for lib, f in args.file_list_vhdl_lib:
            look.write_file_list(Path(f), FileObjType.VHDL, lib)

    if args.ext_file_list is not None:
        look.write_ext_file_list(Path(args.ext_file_list))

    if args.ext_file_list_tag is not None:
        for tag, f in args.ext_file_list_tag:
            look.write_ext_file_list(Path(f), tag)

    if args.compile_order is not None:
        assert(look.has_top_file())
        assert isinstance(look, LookupPrj)
        look.write_compile_order(Path(args.compile_order))

    if args.compile_order_path_only is not None:
        assert(look.has_top_file())
        assert isinstance(look, LookupPrj)
        look.write_compile_order_lib(Path(args.compile_order_poath_only), None)

    if args.compile_order_type is not None:
        assert(look.has_top_file())
        assert isinstance(look, LookupPrj)
        for f_type_str, file_out_str in args.compile_order_type:
            f_type = string_to_FileObjType(f_type_str)
            loc = Path(file_out_str)
            if f_type == FileObjType.VHDL:
                look.write_compile_order(loc, f_type)
            else:
                look.write_compile_order_lib(loc, LIB_DEFAULT, f_type)

    if args.compile_order_vhdl_lib is not None:
        assert(look.has_top_file())
        assert isinstance(look, LookupPrj)
        for lib, f in args.compile_order_vhdl_lib:
            look.write_compile_order_lib(Path(f), lib, FileObjType.VHDL)

    if args.compile_order_json is not None:
        assert(look.has_top_file())
        assert isinstance(look, LookupPrj)
        look.write_compile_order_json(Path(args.compile_order_json))

if __name__ == "__main__":
    hdldepends()
# }}}
