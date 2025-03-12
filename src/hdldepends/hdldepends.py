# vi: foldmethod=marker
import re
import sys
import glob
import json
import pickle
import hashlib
import chardet
import fnmatch
try: import tomllib
except ModuleNotFoundError: import tomli as tomllib
import argparse
import subprocess
from pathlib import Path
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Union, List, Tuple, Set


#created own crapy logger because logging doesn't work with f strings {{{

log_level = 0

class log:
    def _log(severity, *args, **kwargs):
        print(f'[{severity}]', *args, **kwargs, file=sys.stderr)

    def error(*args, **kwargs):
        log._log('ERROR', *args, **kwargs)

    def warning(*args, **kwargs):
        if log_level >= 0:
            log._log('WARNING', *args, **kwargs)

    def info(*args, **kwargs):
        if log_level >= 1:
            log._log('INFO', *args, **kwargs)

    def debug(*args, **kwargs):
        if log_level >= 2:
            log._log('DEBUG', *args, **kwargs)
#}}}

# Utility function {{{
def detect_encoding(file_path:Path):
    with open(file_path, 'rb') as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        return result['encoding']

def path_from_dir(dir: Path, loc: Path):
    if not loc.is_absolute():
        loc = dir / loc
    return loc


def get_file_modification_time(f: Path) -> int:
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
        return make_list(v)


# }}}

def process_glob_patterns(patterns: List[str], base_path: str = ".") -> List[Path]: # {{{
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
    base_path = Path(base_path).resolve()  # Get absolute path of base directory
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
            current_files.update(Path(f).resolve() for f in matched_files)

    # Return sorted list of absolute paths
    return sorted(current_files)
# }}}

LIB_DEFAULT = 'work'
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
    def get_vhdl_package(self, name: Name, f_obj_required_by : Optional["FileObj"]):
        pass

    def get_entity(self, name: Name, f_obj_required_by : Optional["FileObj"]):
        pass

    def add_loc(self, loc: Path, f_obj: "FileObj"):
        pass
#}}}

# Constructs to handle files {{{
# class FileType(Enum):
#     VHDL = auto()
#     VERILOG = auto()

class FileObjType(Enum):
    VHDL = auto()
    VERILOG = auto()
    OTHER = auto()

class FileObj:
    def __init__(self, loc: Path):
        self.loc = loc.resolve()
        self.lib = LIB_DEFAULT
        self.entities: List[Name] = []
        self.entity_deps: List[Name] = []
        self.modification_time =  self.get_modification_time_on_disk()
        self.f_type : Optional[FileObjType] = None
        self.level = None

    def requires_update(self):
        return self.get_modification_time_on_disk() != self.modification_time

    def get_modification_time_on_disk(self):
        return get_file_modification_time(self.loc)

    def replace(self, f_obj : 'FileObj'):
        self.__dict__.update(f_obj.__dict__) #this didn't work

    @property
    def file_type_str(self):
        return "Unknown"

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


    def _get_compile_order(
        self, look: Lookup, files_passed=[], components_missed=[], level=0
    ) -> List['FileObj']:
        files_passed.append(self)
        if self.loc in look.files_2_skip_from_order:
            return []
        order: List[FileObj] = []
        for f_obj in self.get_file_deps(look):
            if f_obj not in files_passed:
                order += f_obj._get_compile_order(look, files_passed, components_missed = components_missed, level = level + 1)
        
        order.append(self)
        self.level = level
        return order

    def get_compile_order(self, look: Lookup) -> List['FileObj']:
        return self._get_compile_order(look)

    def update(self) -> Tuple[bool, bool]:
        """Returns True if the dependencies have changed, Returns True if file was modified"""
        if self.requires_update():
            equivalent = True
            if isinstance(self, FileObjVhdl) or isinstance(self, FileObjVerilog):
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
    def __init__(self, loc: Path):
        super().__init__(loc)
        self.f_type : Optional[FileObjType] = FileObjType.OTHER

    @property
    def file_type_str(self):
        return "Other"


class FileObjVerilog(FileObj):

    @dataclass
    class VInc:
        name : str
        is_sys : bool

    def __init__(self, loc: Path):
        super().__init__(loc)
        self.verilog_includes : List[FileObjVerilog.VInc] = []
        self.f_type : Optional[FileObjType] = FileObjType.VERILOG

    @property
    def file_type_str(self):
        return "Verilog"

    def register_with_lookup(self, look: Lookup, skip_loc : bool = False):
        super().register_with_lookup(look, skip_loc)
        look.add_verilog_file_name(self.loc.name, self)

    def get_file_deps(self, look: Lookup) -> List[FileObj]:
        file_deps = super().get_file_deps(look)
        # file_deps += self.get_verilog_include_deps(look)
        return file_deps

    def get_verilog_include_deps(self, look : Lookup) -> List[FileObj]:
        file_deps = []

        for name, is_sys in self.verilog_includes:
            f_obj = look.get_verilog_file(name, self)
            if f_obj is not None:
                self._add_to_f_deps(file_deps, f_obj)
            else:
                if is_sys:
                    log.warning('could not find sys include')
                else:
                    log.error('could not find sys include')
        return file_deps

    def parse_file_again(self)->FileObj:
        return parse_verilog_file(None, self.loc)


    def equivalent(self, other : FileObj):
        if not isinstance(other, FileObjVerilog):
            return False

        result = (self.loc      == other.loc
            and self.verilog_includes == other.verilog_includes
            and self.entities == other.entities
            and self.entity_deps == other.entity_deps)
            #modificaiton time and level are not checked
        return result
        

class FileObjVhdl(FileObj):

    def __init__(self, loc: Path, lib: str):
        super().__init__(loc)
        self.lib = lib
        self.vhdl_packages: List[Name] = []
        self.vhdl_component_decl: List[str] = []
        self.vhdl_component_deps: List[str] = []
        self.vhdl_package_deps: List[Name] = []
        self.f_type : Optional[FileObjType] = FileObjType.VERILOG

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
                for f_obj in file_package_deps:
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
        return parse_vhdl_file(None, self.loc, self.lib)


    def equivalent(self, other : FileObj):
        if not isinstance(other, FileObjVhdl):
            return False

        result = (self.loc      == other.loc
            and self.lib      == other.lib
            and self.vhdl_packages == other.vhdl_packages
            and self.entities == other.entities
            and self.vhdl_package_deps == other.vhdl_package_deps
            and self.entity_deps == other.entity_deps)
            #modificaiton time and level are not checked
        return result

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

        log.error(f"Conflict on key {key} could not resolve between")
        log.error(f"  (please resolve buy adding the one of the files to the prject toml):")
        for loc in self.loc_2_file_obj.keys():
            log.error(f"\t{loc}")


FileObjLookup = Union[ConflictFileObj, FileObj]

# }}}

def vhdl_remove_comments(verilog_code):
    # Remove single-line comments
    code_without_single_comments = re.sub(r'--.*$', '', verilog_code, flags=re.MULTILINE)
    
    # Remove multi-line comments
    code_without_comments = re.sub(r'/\*.*?\*/', '', code_without_single_comments, flags=re.DOTALL)
    
    return code_without_comments


# VHDL file parsing {{{
vhdl_regex_patterns = {
    "package_decl": re.compile(
        r"\s*package\s+(\w+)\s+is.*?end\s+(?:package|\1)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "entity_decl": re.compile(
        r"\s*entity\s+(\w+)\s+is.*?end\s+(?:entity|\1)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "vhdl_component_decl": re.compile(
        r"\s*component\s+(\w+)\s+(?:is|).*?end\s+(?:component|\1)",
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
        r"^(?!\s*--)\s*use\s+(\w+)\.(\w+)\.\w+\s*;", re.IGNORECASE | re.MULTILINE
    ),
}

def parse_vhdl_file(look: Optional[Lookup], loc: Path, lib=LIB_DEFAULT) -> FileObjVhdl:
    """ Function to find matches in the VHDL code """

    log.info(f"passing VHDL file {loc}:")
    with open(loc, "r") as file:
        vhdl = file.read()

    vhdl = vhdl_remove_comments(vhdl)
    f_obj = FileObjVhdl(loc, lib=lib)

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
                component = item[1]
                if component not in f_obj.vhdl_component_deps:
                    log.debug(f'VHDL {loc} component {component}')
                    f_obj.vhdl_component_deps.append(component)
        elif construct == "direct_inst":
            for item in found:
                l = item[1]
                if l == LIB_DEFAULT:
                    l = lib
                name = Name(l, item[2])
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
        else:
            raise Exception(f"error construct '{construct}'")

    if look is not None:
        f_obj.register_with_lookup(look)
    return f_obj


# }}}

# Pre-process Verilog code to remove comments
def verilog_remove_comments(verilog_code):
    # Remove single-line comments
    code_without_single_comments = re.sub(r'//.*$', '', verilog_code, flags=re.MULTILINE)
    
    # Remove multi-line comments
    code_without_comments = re.sub(r'/\*.*?\*/', '', code_without_single_comments, flags=re.DOTALL)
    
    return code_without_comments

# Function to extract module instantiations from Verilog code
def verilog_extract_module_instantiations(verilog_code):
# Regular expression to find module instantiations and extract the module name
# This matches both named and unnamed instantiations
    # module_instantiation_regex = r'(\w+)\s+(?:#\s*\([^)]*\)\s+)?(?:(\w+)\s*)?\(' #)
    module_instantiation_regex = r'(\w+)\s+(?:#\s*\([^)]*\)\s+)?(\w+)(?:\s+#\s*\([^)]*\))?\s*\(' #)
    matches = re.finditer(module_instantiation_regex, verilog_code)
    instantiations = []
    
    for match in matches:
        module_name = match.group(1)
        instance_name = match.group(2) if match.group(2) else "unnamed"

        VERLOG_RESERVED_WORDS = [ "always", "always_comb", "always_ff", "always_latch", "assign", "begin", "case", "else", "end", "endcase", "endfunction", "endmodule", "endprimitive", "endtable", "endtask", "enum", "for", "forever", "function", "if", "initial", "input", "int", "localparam", "logic", "module", "negedge", "output", "parameter", "posedge", "primitive", "real", "reg", "repeat", "table", "task", "time", "timescale", "typedef", "while", "wire",]
                
        # Filter out Verilog keywords and module declarations that might be mistaken for instantiations
        if module_name not in VERLOG_RESERVED_WORDS and instance_name not in VERLOG_RESERVED_WORDS:
            instantiations.append(module_name)
            instantiations.append(module_name)
    
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

def parse_verilog_file(look : Optional[Lookup], loc : Path) -> FileObjVerilog:
    log.info(f"passing Verilog file {loc}:")

    if loc.suffix != '.v':
        log.warning(f'unexpected verilog extension on {loc} expected .v')

    with open(loc, "r", encoding=detect_encoding(loc)) as file:
        verilog_code = file.read()

    clean_code = verilog_remove_comments(verilog_code)

    
    f_obj = FileObjVerilog(loc)
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


class LookupSingular(Lookup): # {{{
    TOML_KEYS = [
        "pre_cmds",
        "ignore_libs",
        "ignore_packages",
        "ignore_entities",
        "ignore_components",
        "package_file_skip_order",
        "vhdl_files",
        "vhdl_files_file",
        "vhdl_files_glob",
        "verilog_files",
        "verilog_files_file",
        "verilog_files_glob",
        "other_files_file",
        "other_files_glob"
    ]
    VERSION = 2

    def __init__(self, allow_duplicates: bool = True):
        log.debug('LookupSingular::__init__')
        self.version = LookupSingular.VERSION
        self.allow_duplicates = allow_duplicates
        self.package_name_2_file_obj: dict[Name, FileObjLookup] = {}
        self.entity_name_2_file_obj: dict[Name, FileObjLookup] = {}
        self.loc_2_file_obj: dict[Path, FileObjLookup] = {}
        self.verilog_file_name_2_file_obj : dict[str : FileObjVerilog] = {}
        self.ignore_set_libs: Set[str] = set()
        self.ignore_set_packages: Set[Name] = set()
        self.ignore_set_entities: Set[Name] = set()
        self.toml_loc: Optional[Path] = None
        self.toml_modification_time = None
        self.top_lib : Optional[str] = None
        self.ignore_components : Set[str] = set()
        self.files_2_skip_from_order : Set[Path] = set()
        self.vhdl_file_list = None
        self.verilog_file_list = None
        self.other_file_list = None


    def _add_to_dict(self, d: dict, key, f_obj: FileObj):
        log.info(f'Adding {key} to dict')
        if key in d:
            if not self.allow_duplicates:
                raise Exception(f"ERROR: tried to add {key} twice")
            item = d[key]
            if isinstance(item, FileObj):
                conflict_obj = ConflictFileObj((item, f_obj))
            elif isinstance(item, ConflictFileObj):
                conflict_obj = item
                conflict_obj.add_f_obj(f_obj)
            d[key] = conflict_obj
        else:
            d[key] = f_obj

    @staticmethod
    def toml_loc_to_pickle_loc(toml_loc: Path) -> Path:
        pickle_loc = toml_loc.with_suffix(".pickle")
        return pickle_loc

    @staticmethod
    def atempt_to_load_from_pickle(
            pickle_loc: Path, toml_loc: Path, top_lib : Optional[str]
    ) -> Optional[object]:
        assert toml_loc.is_file()
        if not pickle_loc.is_file():
            log.debug('will not load from pickle no file at {pickle_loc}')
            return None, None, None, None
        log.info(f"atempting to load cache from {pickle_loc}")
        pickle_mod_time = get_file_modification_time(pickle_loc)

        with open(pickle_loc, "rb") as pickle_f:
            inst = pickle.load(pickle_f)

        if LookupSingular.VERSION != inst.version:
            log.info(f'hdldepends version { LookupSingular.VERSION} but pickle top_lib {inst.version} will not load from pickle')
            return None, None, None, None

        toml_modification_time = get_file_modification_time(toml_loc)
        if toml_modification_time != inst.toml_modification_time:
            log.info(f"will not load from pickle as {toml_loc} out of date")
            return None, None, None, None

        if top_lib != inst.top_lib:
            log.info(f'requested top_lib {top_lib} but pickle top_lib {inst.top_lib} will not load from pickle')
            return None, None, None, None

        config = load_config(toml_loc)

        vhdl_file_list = LookupSingular.get_vhdl_file_list_from_config_dict(
            config, toml_loc.parent, top_lib
        )
        if vhdl_file_list != inst.vhdl_file_list:
            log.info(f'Will not load from pickle as vhdl_file_list has changed')
            return None, vhdl_file_list, None, None

        verilog_file_list = LookupSingular.get_verilog_file_list_from_config_dict(
            config, toml_loc.parent, top_lib
        )
        if verilog_file_list != inst.verilog_file_list:
            log.info(f'Will not load from pickle as verilog_file_list has changed')
            return None, vhdl_file_list, verilog_file_list, None

        other_file_list = LookupSingular.get_other_file_list_from_config_dict(
            config, toml_loc.parent, top_lib=top_lib
        )

        if other_file_list != inst.other_file_list:
            log.info(f'Will not load from pickle as other_file_list has changed')
            return None, vhdl_file_list, verilog_file_list, other_file_list
        
        log.info(f"loaded from {pickle_loc}, updating required files")
        any_changes = inst.check_for_src_files_updates()
        if any_changes:
            log.info(f"Updating pickle wtih the changes detected on disk")
            inst.save_to_pickle(pickle_loc)
        return inst, vhdl_file_list, verilog_file_list, other_file_list

    def save_to_pickle(self, pickle_loc: Path):
        log.info(f"Caching to {pickle_loc}")
        with open(pickle_loc, "wb") as pickle_f:
            pickle.dump(self, pickle_f, protocol=pickle.HIGHEST_PROTOCOL)

    def check_for_src_files_updates(self) -> bool:
        """Returns True if there where any changes"""
        compile_order_out_of_date = False
        any_changes = False
        for _, f_obj in self.loc_2_file_obj.items():
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
                f_obj.register_with_lookup(self, skip_loc=True)
        
        return any_changes

    @staticmethod
    def _process_config_opt_lib(config: dict, key: str, callback, top_lib : Optional[str]):
        if top_lib is None:
            top_lib = LIB_DEFAULT
        if key not in config:
            return
        c_val = config[key]
        if isinstance(c_val, dict):
            for lib, val in c_val.items():
                if isinstance(val, List):
                    for v in val:
                        callback(lib, v)
                else:
                    callback(lib, val)
        elif isinstance(c_val, List):
            for v in c_val:
                callback(top_lib, v)
        else:
            callback(top_lib, c_val)

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

    def extract_set_name_from_config(
        config: dict, key: str, top_lib : Optional[str]
    ) -> Set[Name]:
        l = []

        def call_back_func(lib: str, name: str):
            l.append(Name(lib=lib, name=name))

        LookupSingular._process_config_opt_lib(config, key, call_back_func,top_lib=top_lib)
        log.info(f"{key} = {l}")
        return set(l)

    def initalise_from_config_dict(self, config: dict, work_dir : Path, top_lib : Optional[str], vhdl_file_list=None, verilog_file_list=None, other_file_list=None):

        if 'top_lib' in config:
            self.top_lib = config['top_lib']
        self.ignore_set_libs = LookupSingular.extract_set_str_from_config(
            config, "ignore_libs"
        )
        self.ignore_set_packages = LookupSingular.extract_set_name_from_config(
            config, "ignore_packages", top_lib=top_lib
        )
        self.ignore_set_entities = LookupSingular.extract_set_name_from_config(
            config, "ignore_entities", top_lib=top_lib
        )
        if 'ignore_components' in config:
            self.ignore_components = make_set(config['ignore_components'])

        if vhdl_file_list is None:
            vhdl_file_list = LookupSingular.get_vhdl_file_list_from_config_dict(
                config, work_dir, top_lib
            )

        if verilog_file_list is None:
            verilog_file_list = LookupSingular.get_verilog_file_list_from_config_dict(
                config, work_dir, top_lib
            )

        if other_file_list is None:
            other_file_list = LookupSingular.get_other_file_list_from_config_dict(
                config, work_dir, top_lib=top_lib
            )

        def add_file_to_list_skip_order(lib, loc_str):
            loc = path_from_dir(work_dir, Path(loc_str))
            loc = loc.resolve()
            self.files_2_skip_from_order.add(loc)

        LookupSingular._process_config_opt_lib(
            config, "package_file_skip_order", add_file_to_list_skip_order, top_lib=top_lib
        )

        self.register_vhdl_file_list(vhdl_file_list)
        self.register_verilog_file_list(verilog_file_list)
        self.register_other_file_list(other_file_list)

    @staticmethod
    def get_vhdl_file_list_from_config_dict(config: dict, work_dir: Path, top_lib : Optional[str]):
        log.debug(f'called get_vhdl_file_list_from_config_dict( top_lib={top_lib} )')
        vhdl_file_list = []

        def add_file_to_list(lib, loc_str):
            loc = path_from_dir(work_dir, Path(loc_str))
            vhdl_file_list.append((lib, loc))

        LookupSingular._process_config_opt_lib(config, "vhdl_files", add_file_to_list, top_lib=top_lib)

        def add_file_to_list_skip_order(lib, loc_str):
            loc = path_from_dir(work_dir, Path(loc_str))
            vhdl_file_list.append((lib, loc))

        LookupSingular._process_config_opt_lib(
            config, "package_file_skip_order", add_file_to_list_skip_order, top_lib=top_lib
        )
        

        def add_file_list_to_list(lib, f_str):
            fl_loc = Path(f_str)
            fl_loc = path_from_dir(work_dir, fl_loc).resolve()
            with open(fl_loc, "r") as f_list_file:
                for loc_str in f_list_file:
                    loc_str = loc_str.strip()
                    loc = path_from_dir(fl_loc.parents[0], Path(loc_str))
                    vhdl_file_list.append((lib, loc))

        LookupSingular._process_config_opt_lib(
            config, "vhdl_files_file", add_file_list_to_list, top_lib=top_lib
        )

        glob_str_dict = {}
        def add_to_glob_str_dict(lib, glob_str):
            if lib not in glob_str_dict:
                glob_str_dict[lib] = []
            glob_str_dict[lib].append(glob_str)

        LookupSingular._process_config_opt_lib(
            config, "vhdl_files_glob", add_to_glob_str_dict, top_lib=top_lib
        )

        for lib, glob_str_list in glob_str_dict.items():
            loc_rel_list = process_glob_patterns(glob_str_list, work_dir)
            for loc_rel in loc_rel_list:
                loc = path_from_dir(work_dir, loc_rel).resolve()
                vhdl_file_list.append((lib, loc))
        
        return vhdl_file_list

    @staticmethod
    def get_verilog_file_list_from_config_dict(config: dict, work_dir: Path, top_lib : Optional[str]):
        log.debug(f'called get_verilog_file_list_from_config_dict( top_lib={top_lib} )')
        verilog_file_list_w_lib = []

        def add_file_to_list(lib, loc_str):
            loc = path_from_dir(work_dir, Path(loc_str))
            verilog_file_list_w_lib.append((lib, loc))

        LookupSingular._process_config_opt_lib(config, "verilog_files", add_file_to_list, top_lib=top_lib)

        def add_file_list_to_list(lib, f_str):
            fl_loc = Path(f_str)
            fl_loc = path_from_dir(work_dir, fl_loc).resolve()
            with open(fl_loc, "r") as f_list_file:
                for loc_str in f_list_file:
                    loc_str = loc_str.strip()
                    loc = path_from_dir(fl_loc.parents[0], Path(loc_str))
                    verilog_file_list_w_lib.append((lib, loc))

        LookupSingular._process_config_opt_lib(
            config, "verilog_files_file", add_file_list_to_list, top_lib=top_lib
        )

        glob_str_dict = {}
        def add_to_glob_str_dict(lib, glob_str):
            if lib not in glob_str_dict:
                glob_str_dict[lib] = []
            glob_str_dict[lib].append(glob_str)

        LookupSingular._process_config_opt_lib(
            config, "verilog_files_glob", add_to_glob_str_dict, top_lib=top_lib
        )

        for lib, glob_str_list in glob_str_dict.items():
            loc_rel_list = process_glob_patterns(glob_str_list, work_dir)
            for loc_rel in loc_rel_list:
                loc = path_from_dir(work_dir, loc_rel).resolve()
                verilog_file_list_w_lib.append((lib, loc))
        
        for lib, loc in verilog_file_list_w_lib:
            if lib != LIB_DEFAULT:
                log.error(f"Verilog does not support libraries got lib {lib} on file {loc}")
        verilog_file_list = [a[1] for a in verilog_file_list_w_lib]

        log.debug(f'get_verilog_file_list_from_config_dict returns {verilog_file_list=}')
        return verilog_file_list

    @staticmethod
    def get_other_file_list_from_config_dict(config: dict, work_dir: Path, top_lib : Optional[str]):
        other_File_list_w_lib = []
        def add_ext_dep_file_to_list(lib, f_str):
            fl_loc = Path(f_str)
            fl_loc = path_from_dir(work_dir, fl_loc).resolve()
            with open(fl_loc, "r") as f_list_file:
                for loc_str in f_list_file:
                    loc_str = loc_str.strip()
                    loc = path_from_dir(fl_loc.parents[0], Path(loc_str))
                    other_File_list_w_lib.append((lib, loc))
                    
        LookupSingular._process_config_opt_lib(
            config, "other_files_file", add_ext_dep_file_to_list, top_lib=top_lib
        )
        
        glob_str_dict = {}
        def add_to_glob_str_dict(lib, glob_str):
            if lib not in glob_str_dict:
                glob_str_dict[lib] = []
            glob_str_dict[lib].append(glob_str)

        LookupSingular._process_config_opt_lib(
            config, "other_files_glob", add_to_glob_str_dict, top_lib=top_lib
        )

        for lib, glob_str_list in glob_str_dict.items():
            loc_rel_list = process_glob_patterns(glob_str_list, work_dir)
            for loc_rel in loc_rel_list:
                loc = path_from_dir(work_dir, loc_rel).resolve()
                other_File_list_w_lib.append((lib, loc))

        for lib, loc in other_File_list_w_lib:
            if lib != LIB_DEFAULT:
                log.error(f'Files types not VHDL must have default library {LIB_DEFAULT} got library {lib} on file {loc}')

        return [loc for _, loc in other_File_list_w_lib]

    def register_other_file_list(self, other_file_list):
        self.other_file_list = other_file_list
        for loc in other_file_list:
            
            f_obj = FileObjOther(loc=loc)
            entity_name = Name(LIB_DEFAULT, loc.stem)
            f_obj.entities.append(entity_name)
            self.entity_name_2_file_obj[entity_name] = f_obj
            self.loc_2_file_obj[loc] = f_obj

    def register_vhdl_file_list(self, vhdl_file_list : List[Tuple[str, Path]]):
        self.vhdl_file_list = vhdl_file_list
        print(f'NEW: {self.vhdl_file_list=}')
        for lib, loc in vhdl_file_list:
            parse_vhdl_file(self, loc, lib=lib)

    def register_verilog_file_list(self, verilog_file_list : List[Path]):
        self.verilog_file_list = verilog_file_list
        for loc in verilog_file_list:
            parse_verilog_file(self, loc)

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
        loc = loc.resolve()
        self._add_to_dict(self.loc_2_file_obj, loc, f_obj)

    def add_verilog_file_name(self, file_name: str, f_obj : FileObjVerilog):
        self._add_to_dict(self.verilog_file_name_2_file_obj, file_name, f_obj)

    def get_loc(self, loc: Path):
        loc = loc.resolve()
        return self.loc_2_file_obj[loc]

    def has_loc(self, loc: Path):
        loc = loc.resolve()
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
            item.log_confict(name)
            raise KeyError(f"ERROR: confict on entity {name} required by {loc_str}")

    def get_top_lib(self):
        return self.top_lib

    def set_top_lib(self, top_lib : Optional[str] = None):
        self.top_lib = top_lib

    def get_file_list(self, lib:Optional[str]=None):
        file_list = []
        for f_obj in self.loc_2_file_obj.values():
            if f_obj.loc in look.files_2_skip_from_order:
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
#}}}

class LookupMulti(LookupSingular):  # {{{
    TOML_KEYS = ["sub"]

    def __init__(
            self, look_subs: List[LookupSingular]): #, file_list: List[Tuple[str, Path]] = [] ):
        log.debug('LookupMulti::__init__')
        self.look_subs = look_subs
        super().__init__(allow_duplicates=True)
        self.f_obj_top = None
        self._compile_order = None

    @staticmethod
    def create_from_config_dict(
            config: dict, work_dir: Path, look_subs=[], **kwargs
    ):

        look = LookupMulti(look_subs)
        look.initalise_from_config_dict(config, work_dir, **kwargs)
        return look

    def register_vhdl_file_list(self, vhdl_file_list:List[Tuple[Path,str]]):
        self.vhdl_file_list = vhdl_file_list
        for lib, loc in vhdl_file_list:
            f_obj = self._get_loc_from_common(loc)
            if f_obj is not None:
                assert f_obj.lib == lib
                f_obj.register_with_lookup(self)
            else:
                # not passed in common lookup pass in prj lookup
                f_obj = parse_vhdl_file(self, loc, lib=lib)

    def register_verilog_file_list(self, verilog_file_list:List[Path]):
        log.debug(f'register_verilog_file_list({verilog_file_list=}) called')
        self.verilog_file_list = verilog_file_list
        for loc in verilog_file_list:
            f_obj = self._get_loc_from_common(loc)
            if f_obj is not None:
                f_obj.register_with_lookup(self)
            else:
                f_obj = parse_verilog_file(self, loc)



    def get_loc(self, loc: Path, lib_to_add_to_if_not_found: Optional[str] = None):
        try:
            return super().get_loc(loc)
        except KeyError:
            f_obj = self._get_loc_from_common(loc)
            if f_obj is not None:
                return f_obj
            if lib_to_add_to_if_not_found is not None:
                f_obj = parse_vhdl_file(
                    self, loc, lib=lib_to_add_to_if_not_found
                )
                return f_obj
            else:
                raise KeyError(f"file {loc} not found in dependency lookups")


    def _get_loc_from_common(self, loc: Path) -> Optional[FileObj]:
        for l_common in self.look_subs:
            if l_common.has_loc(loc):
                return l_common.get_loc(loc)
        return None

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
            return LookupSingular.get_vhdl_package(self, name, f_obj_required_by)

        call_back_func_arr = [cb] + [l.get_vhdl_package for l in self.look_subs]
        return self._get_named_item("package", name, call_back_func_arr, f_obj_required_by)

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
    TOML_KEYS = ["top_vhdl_file", "top_verilog_file", "top_entity"]

    def __init__(
            self, look_subs: List[LookupMulti]) : #, file_list: List[Tuple[str, Path]] = [] ):
        log.debug('LookupPrj::__init__')
        super().__init__(look_subs)
        self.f_obj_top = None
        self._compile_order = None

    def set_top_lib(self, top_lib : Optional[str]):
        self._compile_order = None
        super().set_top_lib(top_lib)

    @staticmethod
    def create_from_config_dict(
            config: dict, work_dir: Path, look_subs=[], top_lib=None, **kwargs
    ):

        look = LookupPrj(look_subs)
        look.initalise_from_config_dict(config, work_dir, top_lib=top_lib, **kwargs)

        if "top_vhdl_file" in config and "top_verilog_file" in config:
            raise RuntimeError("Only top_vhdl_file or top_verilog_file file is supported")

        if "top_vhdl_file" in config:

            l = []

            def call_back_func(lib: str, loc_str: str):
                loc_str = work_dir / loc_str
                n = (lib, loc_str)
                if len(l) != 0:
                    raise Exception(f"only supports one top_vhdl_file got {l[0]} and {n}")
                l.append(n)

            LookupSingular._process_config_opt_lib(config, "top_vhdl_file", call_back_func, top_lib=top_lib)

            assert len(l) == 1
            
            lib = l[0][0]
            loc = Path(l[0][1])
            look.set_top_vhdl_file(loc, lib)

        if "top_verilog_file" in config:

            l = []

            def call_back_func(lib: str, loc_str: str):
                loc_str = work_dir / loc_str
                n = (lib, loc_str)
                if len(l) != 0:
                    raise Exception(f"only supports one top_verilog_file got {l[0]} and {n}")
                l.append(n)

            LookupSingular._process_config_opt_lib(config, "top_verilog_file", call_back_func, top_lib=top_lib)

            assert len(l) == 1
            
            lib = l[0][0]
            loc = Path(l[0][1])
            if lib != LIB_DEFAULT:
                log.error(f'verilog does not support libraries got lib {lib}')
            look.set_top_verilog_file(loc)

        if "top_entity" in config:
            name_list = []
            def call_back_func(lib: str, name_str: str):
                name = Name(lib, name_str)
                if len(name_list) != 0:
                    raise Exception(f"only supports one entity but got {name_list[0]} and {n}")
                name_list.append(name)

            LookupSingular._process_config_opt_lib(config, "top_entity", call_back_func, top_lib=top_lib)
            assert len(name_list) == 1
            name = name_list[0]
            look.set_top_entity(name, do_not_replace_top_file=True)

        return look

    def set_top_vhdl_file(self, loc: Path, lib=None):
        self.f_obj_top = self.get_loc(loc, lib_to_add_to_if_not_found=lib)
        self._compile_order = None

    def set_top_verilog_file(self, loc: Path, lib=None):
        self.f_obj_top = self.get_loc(loc, lib_to_add_to_if_not_found=lib)
        self._compile_order = None


    def set_top_entity(self, name, do_not_replace_top_file=True):
        if do_not_replace_top_file and self.f_obj_top is not None:
            f_obj = self.get_entity(name, f_obj_required_by=None)
            if f_obj != self.f_obj_top:
                raise RuntimeError(f'cound not find entity {top_ent_name} in file {loc}')

        else:
            f_obj = self.get_entity(name, f_obj_required_by=None)
            if isinstance(f_obj, FileObjVhdl):
                log.info(f'top_entity {name} found in vhdl file {f_obj.loc}')
                self.set_top_vhdl_file(f_obj.loc, f_obj.lib)
            elif isintance(f_obj, FileObjVerilog):
                log.info(f'top_entity {name} found in verilog file {f_obj.loc}')
                self.set_top_verilog_file(f_obj.loc)
            else:
                raise RuntimeError(f'Unexpected file object type {type(f_obj)} for top level module')

    def has_top_file(self) -> bool:
        return self.f_obj_top is not None

    @property
    def compile_order(self):
        if self._compile_order is None:
            if self.f_obj_top is None:
                raise Exception(
                    "top_file must be declared in config or on command line"
                )

            self._compile_order = self.f_obj_top.get_compile_order(self)
        return self._compile_order

    def print_compile_order(self):
        print("compile order:")
        for f_obj in self.compile_order:
            print(f'  {f_obj.file_type_str+":":10} {"|---"*f_obj.level}{f_obj.lib}:{f_obj.loc}')

    def write_compile_order(self, compile_order_loc: Path, f_type : Optional[FileObjType]=None):
        with open(compile_order_loc, "w") as f_order:
            for f_obj in self.compile_order:
                if f_type is not None:
                    if f_obj.f_type != f_type:
                        continue
                f_order.write(f"{f_obj.lib} {f_obj.loc}\n")

    def write_compile_order_lib(self, compile_order_loc: Path, lib:str, f_type: Optional[FileObjType]=None):
        lines = 0
        with open(compile_order_loc, "w") as f_order:
            for f_obj in self.compile_order:
                if f_type is not None:
                    if f_obj.f_type != f_type:
                        continue
                if lib == f_obj.lib:
                    f_order.write(f"{f_obj.loc}\n")
                    lines += 1
        if lines == 0:
            log.warning(f'not files found for libarary {lib}')
#}}}

# Handling of configuration files {{{
def load_config(toml_loc):
    is_json = toml_loc.suffix == '.json'
    with open(toml_loc, "rb") as toml_f:
        if is_json:
            return json.load(toml_f)
        else:
            return tomllib.load(toml_f)

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
        temp_dir = work_dir.resolve()
        test = temp_dir / toml_loc
        while not test.is_file():
            temp_dir = temp_dir.parents[0]
            test = temp_dir / toml_loc
            if test == Path("/"):
                raise FileNotFoundError(f"ERROR could not find file {toml_loc}")
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

    vhdl_file_list = None
    verilog_file_list = None
    other_file_list = None
    if attemp_read_pickle:
        inst, vhdl_file_list, verilog_file_list, other_file_list = LookupSingular.atempt_to_load_from_pickle(pickle_loc, toml_loc, top_lib=top_lib)
        if inst is not None:
            inst.look_subs = look_subs
            return inst

    # picke_loc = LookupSingular.toml_loc_to_pickle_loc(toml_loc)

    error_key = issue_key(LookupPrj.TOML_KEYS + LookupMulti.TOML_KEYS + LookupSingular.TOML_KEYS, config.keys())
    if error_key is not None:
        raise KeyError(f"Got unexpected key {error_key} in file {toml_loc}")

    if force_LookupPrj or contains_any(config.keys(), LookupPrj.TOML_KEYS):

        log.info(f"create LookupPrj from {toml_loc}")
        inst = LookupPrj.create_from_config_dict(
            config, work_dir=work_dir, look_subs=look_subs, top_lib=top_lib, vhdl_file_list=vhdl_file_list, verilog_file_list = verilog_file_list, other_file_list = other_file_list
        )

    elif contains_any(config.keys(), LookupMulti.TOML_KEYS):

        log.info(f"create LookupMulti from {toml_loc}")
        inst = LookupMulti.create_from_config_dict(
            config, work_dir=work_dir, look_subs=look_subs, top_lib=top_lib, vhdl_file_list=vhdl_file_list, verilog_file_list = verilog_file_list, other_file_list = other_file_list
        )

    else :
        inst = LookupSingular.create_from_config_dict(
            config, work_dir=work_dir, top_lib=top_lib, vhdl_file_list=vhdl_file_list, verilog_file_list=verilog_file_list, other_file_list = other_file_list
        )

    print(f'toml_loc {toml_loc}')
    inst.toml_modification_time = get_file_modification_time(toml_loc)

    if write_pickle:
        look_subs = None
        if hasattr(inst, 'look_subs'):
            look_subs = inst.look_subs
        inst.save_to_pickle(pickle_loc)
        if look_subs is not None:
            inst.look_subs = look_subs
    return inst
# }}}

# {{{ Main method handling
def extract_lib_compiler_order(s)-> Tuple[str, str]:
    try:
        lib, f = s.split(':')
        return lib, f
    except:
        print(f's = {s}')
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
    parser.add_argument("--top-vhdl-file", type=str, help="Top level file to use")
    parser.add_argument("--top-verilog-file", type=str, help="Top level file to use")
    parser.add_argument("--top-entity", type=str, help="Top entity to use")
    parser.add_argument("--top-lib", type=str, help="Top level library")
    parser.add_argument(
        "--compile-order", type=str, help="Path to the compile order output file."
    )
    parser.add_argument(
        "--compile-order-vhdl", type=str, help="Path to the VHDL compile order output file."
    )
    parser.add_argument(
        "--compile-order-verilog", type=str, help="Path to the Verilog compile order output file"
    )
    parser.add_argument(
        "--compile-order-lib", nargs ="+", type=extract_lib_compiler_order, help="Expects 'lib:file' where 'file' is location to write the compile order of libary 'lib'."
    )
    parser.add_argument(
        "--compile-order-vhdl-lib", nargs ="+", type=extract_lib_compiler_order, help="Expects 'lib:file' where 'file' is location to write the VHDL compile order of libary 'lib'."
    )
    parser.add_argument(
        "--file-list", type=str, help="Output full file list of in project"
    )
    parser.add_argument(
        "--file-list-vhdl", type=str, help="Output full VHDL file list of in project"
    )
    parser.add_argument(
        "--file-list-verilog", type=str, help="Output Verilog list of in project"
    )
    parser.add_argument(
        "--file-list-lib", nargs ="+", type=extract_lib_compiler_order, help="Expects 'lib:file' where 'file' is location to write the file list of library 'lib'."
    )
    parser.add_argument(
        "--file-list-vhdl-lib", nargs ="+", type=extract_lib_compiler_order, help="Expects 'lib:file' where 'file' is location to write the VHDL file list of library 'lib'."
    )

    args = parser.parse_args()

    if args.top_vhdl_file and args.top_verilog_file:
        raise RuntimeError('set top_vhdl_file or top_verilog_file')

    set_log_level_from_verbose(args)

    work_dir=Path('.')
    top_lib = None
    if args.top_lib:
        top_lib = args.top_lib

    attemp_read_pickle = not args.clear_pickle and not args.no_pickle
    write_pickle = not args.no_pickle
    if args.config_file:
        if len(args.config_file) == 1:
            log.debug('creating top level project toml')
            look = create_lookup_from_toml(Path(args.config_file[0]), work_dir=work_dir,
            force_LookupPrj=True, attemp_read_pickle=attemp_read_pickle, write_pickle=write_pickle, top_lib=top_lib
        )
        else:
            look_subs = []
            for c_toml in look_subs:
                look_subs.append(
                    create_lookup_from_toml(
                        Path(c_toml), work_dir=work_dir, attemp_read_pickle=attemp_read_pickle, write_pickle=write_pickle, top_lib=top_lib
                    )
                )
            look = LookupPrj(look_subs)

    if args.top_vhdl_file:
        look.set_top_vhdl_file(Path(args.top_vhdl_file), "work")

    if args.top_verilog_file:
        look.set_top_verilog_file(Path(args.top_verilog_file))

    if args.top_entity:
        lib = top_lib
        if lib is None:
            lib = 'work'
        name = Name(lib, args.top_entity)
        look.set_top_entity(name, do_not_replace_top_file=True)

    if look.has_top_file():
        look.print_compile_order()

    if args.file_list is not None:
        look.write_file_list(Path(args.file_list))

    if args.file_list_vhdl is not None:
        look.write_file_list(Path(f), FileObjType.VHDL)

    if args.file_list_verilog is not None:
        look.write_file_list(Path(f), FileObjType.VERILOG)

    if args.file_list_lib is not None:
        for lib, f in args.compile_order_vhdl_lib:
            look.write_file_list(Path(f), None, lib)

    if args.file_list_vhdl_lib is not None:
        for lib, f in args.compile_order_lib:
            look.write_file_list(Path(f), FileObjType.VHDL, lib)

    if args.compile_order is not None:
        look.write_compile_order(Path(args.compile_order))

    if args.compile_order_lib is not None:
        for lib, f in args.compile_order_lib:
            look.write_compile_order_lib(Path(f), lib)

    if args.compile_order_vhdl is not None:
        look.write_compile_order(Path(args.compile_order), FileObjType.VHDL)

    if args.compile_order_verilog is not None:
        look.write_compile_order(Path(args.compile_order), FileObjType.VERILOG)

    if args.compile_order_vhdl_lib is not None:
        for lib, f in args.compile_order_vhdl_lib:
            look.write_compile_order_lib(Path(f), lib, FileObjType.VHDL)

if __name__ == "__main__":
    hdldepends()
            
# }}}