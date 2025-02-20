import re
import sys
import glob
import pickle
import hashlib
import json
import fnmatch
import tomllib
import argparse
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Union

log_level = 0

#created own crapy logger because logging doesn't work with f strings
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

regex_patterns = {
    "package_decl": re.compile(
        r"^(?!\s*--)\s*package\s+(\w+)\s+is.*?end\s+(?:package|\1)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "entity_decl": re.compile(
        r"^(?!\s*--)\s*entity\s+(\w+)\s+is.*?end\s+(?:entity|\1)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "component_decl": re.compile(
        r"^(?!\s*--)\s*component\s+(\w+)\s+(?:is|).*?end\s+(?:component|\1)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "component_inst": re.compile(
        r"^(?!\s*--)\s*(\w+)\s*:\s*(\w+)(?:\s*generic\s*map\s*\(.*?\))?\s*port\s*map\s*\(.*?\)\s*;",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "direct_inst": re.compile(
        r"^(?!\s*--)\s*(\w+)\s*:\s*(?:entity\s+)?(\w+)\.(\w+)(?:\s*generic\s*map\s*\(.*?\))?\s*port\s*map\s*\(.*?\)\s*;",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "package_use": re.compile(
        r"^(?!\s*--)\s*use\s+(\w+)\.(\w+)\.\w+\s*;", re.IGNORECASE | re.MULTILINE
    ),
    }


def process_glob_patterns(patterns: list[str], base_path: str = ".") -> list[Path]:
    """
    Process a list of glob patterns sequentially, including exclusion patterns (starting with '!'),
    to generate a filtered list of file paths. Each pattern modifies the current file list.
    
    Args:
        patterns (list[str]): list of glob patterns. Patterns starting with '!' are exclusions.
        base_path (str): Base directory to start glob searches from. Defaults to current directory.
    
    Returns:
        list[str]: list of absolute file paths that match the inclusion patterns but not the exclusion patterns.
    
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



class Name:
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


def path_from_dir(dir: Path, loc: Path):
    if not loc.is_absolute():
        loc = dir / loc
    return loc


def get_file_modification_time(f: Path) -> int:
    return f.lstat().st_mtime

# def get_file_md5sum(f : Path) -> int:
#     with open(f, 'rb') as f_read:
#         data = f_read.read()
#         return hashlib.md5(data).digest()


def str_to_name(s: str):
    l = s.split(".")
    if len(l) == 1:  # no lib use default
        return Name("work", name=l[0])
    elif len(l) == 2:
        return Name(lib=l[0], name=l[1])
    else:
        raise Exception(f"ERROR converting str {s} to Name")


class Lookup:
    def get_package(self, name: Name, f_obj_required_by : Optional["FileObj"]):
        pass

    def get_entity(self, name: Name, f_obj_required_by : Optional["FileObj"]):
        pass

    def add_loc(self, loc: Path, f_obj: "FileObj"):
        pass


class FileObj:

    def __init__(self, loc: Path, lib: str):
        self.loc = loc.resolve()
        self.lib = lib
        self.packages: list[Name] = []
        self.entities: list[Name] = []
        self.component_decl: list[str] = []
        self.component_deps: list[str] = []
        self.package_deps: list[Name] = []
        self.entity_deps: list[Name] = []
        self.level = None
        self.modification_time =  self.get_modification_time_on_disk()

    def register_with_lookup(self, look: Lookup, skip_loc : bool = False):
        for p in self.packages:
            look.add_package(p, self)
        for e in self.entities:
            look.add_entity(e, self)
        if not skip_loc:
            look.add_loc(self.loc, self)

    def get_modification_time_on_disk(self):
        return get_file_modification_time(self.loc)

    @staticmethod
    def _add_to_f_deps(file_deps, f_obj):
        if f_obj not in file_deps:
            file_deps.append(f_obj)

    def get_file_deps(self, look: Lookup) -> list["FileObj"]:
        file_deps = self.get_package_deps(look)

        for e in self.entity_deps:
            f_obj = look.get_entity(e, self)
            if f_obj is not None:
                self._add_to_f_deps(file_deps, f_obj)

        return file_deps

    def get_package_deps(self, look : Lookup) -> list["FileObj"]:
        file_deps = []

        for p in self.package_deps:
            f_obj = look.get_package(p, self)
            if f_obj is not None:
                self._add_to_f_deps(file_deps, f_obj)
        return file_deps

    def get_compile_order(self, look: Lookup) -> list["FileObj"]:
        return self._get_compile_order(look)

    def _get_compile_order(
        self, look: Lookup, files_passed=[], components_missed=[], level=0
    ) -> list["FileObj"]:
        files_passed.append(self)
        if self.loc in look.files_2_skip_from_order:
            return []
        order: list["FileObj"] = []
        for f_obj in self.get_file_deps(look):
            if f_obj not in files_passed:
                order += f_obj._get_compile_order(look, files_passed, components_missed, level + 1)
        if len(self.component_deps) > 0:
            file_package_deps = self.get_package_deps(look)
            for component in self.component_deps:
                if component in look.ignore_components:
                    continue
                found = False
                for f_obj in file_package_deps:
                    if component in f_obj.component_decl:
                        found = True
                        break
                if not found:
                    if component not in components_missed:
                        log.warning(f'File {self.loc} cannot find component declartion for component dependency {component}')
                        components_missed.append(component)

        order.append(self)
        self.level = level
        return order

    def requires_update(self):
        return self.get_modification_time_on_disk() != self.modification_time

    def update(self) -> tuple[bool, bool]:
        """Returns True if the dependencies have changed, Returns True if file was modified"""
        if self.requires_update():
            f_obj = parse_vhdl_file(None, self.loc, self.lib)
            if f_obj.equivalent(self) :
                log.info(f'file {self.loc} updated but dependencies remain unchanaged')
                self.modification_time = f_obj.modification_time
                return False, True
            else:
                log.info(f'file {self.loc} is updated and dependencies have changed')
                self.replace(f_obj)

                return True, True
        return False, False

    def replace(self, f_obj : "FileObj"):
        self.__dict__.update(f_obj.__dict__) #this didn't work


    def equivalent(self, other : "FileObj"):

        result = (self.loc      == other.loc
            and self.lib      == other.lib
            and self.packages == other.packages
            and self.entities == other.entities
            and self.package_deps == other.package_deps
            and self.entity_deps == other.entity_deps)
            #modificaiton time and level are not checked
        return result



IGNORE_SET_LIBS_DEFAULT = {
    "ieee",
}


class ConflictFileObj:
    def __init__(self, conflict_list: list[FileObj]):
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


def make_list(v) -> list:
    if isinstance(v, list):
        return v
    else:
        return [v]


def make_set(v) -> set:
    if isinstance(v, set):
        return v
    else:
        return make_list(v)


class LookupSingular(Lookup):
    TOML_KEYS = [
        "pre_cmds",
        "ignore_libs",
        "ignore_packages",
        "ignore_entities",
        "ignore_components",
        "package_file_skip_order",
        "files",
        "file_list_files",
#        "extern_deps",
        "extern_deps_file",
        "glob_files",
        "glob_extern_deps"
    ]
    VERSION = 1

    def __init__(self, allow_duplicates: bool = True):
        log.debug('LookupSingular::__init__')
        self.version = LookupSingular.VERSION
        self.allow_duplicates = allow_duplicates
        self.package_name_2_file_obj: dict[Name, FileObjLookup] = {}
        self.entity_name_2_file_obj: dict[Name, FileObjLookup] = {}
        self.loc_2_file_obj: dict[Path, FileObjLookup] = {}
        self.ignore_set_libs: set[str] = set()
        self.ignore_set_packages: set[Name] = set()
        self.ignore_set_entities: set[Name] = set()
        self.toml_loc: Optional[Path] = None
        self.toml_modification_time = None
        self.top_lib : Optional[str] = None
        self.ignore_components : set[str] = set()
        self.files_2_skip_from_order : set[Path] = set()
        self.hash_file_list = None
        self.hash_extern_deps_list = None


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
            return None, None, None
        log.info(f"atempting to load cache from {pickle_loc}")
        pickle_mod_time = get_file_modification_time(pickle_loc)

        with open(pickle_loc, "rb") as pickle_f:
            inst = pickle.load(pickle_f)

            if LookupSingular.VERSION != inst.version:
                log.info(f'hdldepends version { LookupSingular.VERSION} but pickle top_lib {inst.version} will not load from pickle')
                return None, None, None

            toml_modification_time = get_file_modification_time(toml_loc)
            if toml_modification_time != inst.toml_modification_time:
                log.info(f"will not load from pickle as {toml_loc} out of date")
                return None, None, None

            if top_lib != inst.top_lib:
                log.info(f'requested top_lib {top_lib} but pickle top_lib {inst.top_lib} will not load from pickle')
                return None, None, None

            config = load_config(toml_loc)

            file_list = LookupSingular.get_file_list_from_config_dict(
                config, toml_loc.parent, top_lib
            )
            hash_file_list = hash(frozenset(file_list))
            if hash_file_list != inst.hash_file_list:
                log.info(f'Will not load from pickle as file_list has changed')
                return None, file_list, None

            extern_deps_list = LookupSingular.get_extern_deps_list_from_config_dict(
                config, toml_loc.parent, top_lib=top_lib
            )
            hash_extern_deps_list = hash(frozenset(extern_deps_list))

            if hash_file_list != inst.hash_file_list:
                log.info(f'Will not load from pickle as extern_deps_list has changed')
                return None, file_list, extern_deps_list
            
            log.info(f"loaded from {pickle_loc}, updating required files")
            any_changes = inst.check_for_src_files_updates()
            if any_changes:
                log.info(f"Updating pickle wtih the changes detected on disk")
                inst.save_to_pickle(pickle_loc)
            return inst, file_list, extern_deps_list
        log.info(f"{pickle_loc} out of date")

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
            top_lib = 'work'
        if key not in config:
            return
        c_val = config[key]
        if isinstance(c_val, dict):
            for lib, val in c_val.items():
                if isinstance(val, list):
                    for v in val:
                        callback(lib, v)
                else:
                    callback(lib, val)
        elif isinstance(c_val, list):
            for v in c_val:
                callback(top_lib, v)
        else:
            callback(top_lib, c_val)

    @staticmethod
    def extract_set_str_from_config(
        config: dict, key: str
    ) -> set[str]:
        if key not in config:
            return set()
        val = config[key]
        result = make_set(val)
        log.info(f"{key} = {list(result)}")
        return result

    def extract_set_name_from_config(
        config: dict, key: str, top_lib : Optional[str]
    ) -> set[Name]:
        l = []

        def call_back_func(lib: str, name: str):
            l.append(Name(lib=lib, name=name))

        LookupSingular._process_config_opt_lib(config, key, call_back_func,top_lib=top_lib)
        log.info(f"{key} = {l}")
        return set(l)

    def initalise_from_config_dict(self, config: dict, work_dir : Path, top_lib : Optional[str], file_list=None, extern_deps_list=None):

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

        if file_list is None:
            file_list = LookupSingular.get_file_list_from_config_dict(
                config, work_dir, top_lib
            )

        if extern_deps_list is None:
            extern_deps_list = LookupSingular.get_extern_deps_list_from_config_dict(
                config, work_dir, top_lib=top_lib
            )

        def add_file_to_list_skip_order(lib, loc_str):
            loc = path_from_dir(work_dir, Path(loc_str))
            loc = loc.resolve()
            self.files_2_skip_from_order.add(loc)

        LookupSingular._process_config_opt_lib(
            config, "package_file_skip_order", add_file_to_list_skip_order, top_lib=top_lib
        )

        self.register_file_list(file_list)
        self.register_extern_deps_list(extern_deps_list)

    @staticmethod
    def get_file_list_from_config_dict(config: dict, work_dir: Path, top_lib : Optional[str]):
        log.debug(f'called get_file_list_from_config_dict( top_lib={top_lib} )')
        file_list = []

        def add_file_to_list(lib, loc_str):
            loc = path_from_dir(work_dir, Path(loc_str))
            file_list.append((lib, loc))

        LookupSingular._process_config_opt_lib(config, "files", add_file_to_list, top_lib=top_lib)

        def add_file_to_list_skip_order(lib, loc_str):
            loc = path_from_dir(work_dir, Path(loc_str))
            file_list.append((lib, loc))

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
                    file_list.append((lib, loc))

        LookupSingular._process_config_opt_lib(
            config, "file_list_files", add_file_list_to_list, top_lib=top_lib
        )

        glob_str_dict = {}
        def add_to_glob_str_dict(lib, glob_str):
            if lib not in glob_str_dict:
                glob_str_dict[lib] = []
            glob_str_dict[lib].append(glob_str)

        LookupSingular._process_config_opt_lib(
            config, "glob_files", add_to_glob_str_dict, top_lib=top_lib
        )

        for lib, glob_str_list in glob_str_dict.items():
            loc_rel_list = process_glob_patterns(glob_str_list, work_dir)
            for loc_rel in loc_rel_list:
                loc = path_from_dir(work_dir, loc_rel).resolve()
                file_list.append((lib, loc))
        
        return file_list

    @staticmethod
    def get_extern_deps_list_from_config_dict(config: dict, work_dir: Path, top_lib : Optional[str]):
        extern_deps_list = []
        def add_ext_dep_file_to_list(lib, f_str):
            fl_loc = Path(f_str)
            fl_loc = path_from_dir(work_dir, fl_loc).resolve()
            with open(fl_loc, "r") as f_list_file:
                for loc_str in f_list_file:
                    loc_str = loc_str.strip()
                    loc = path_from_dir(fl_loc.parents[0], Path(loc_str))
                    extern_deps_list.append((lib, loc))
                    
        # "extern_deps", #TODO
        LookupSingular._process_config_opt_lib(
            config, "extern_deps_file", add_ext_dep_file_to_list, top_lib=top_lib
        )
        
        glob_str_dict = {}
        def add_to_glob_str_dict(lib, glob_str):
            if lib not in glob_str_dict:
                glob_str_dict[lib] = []
            glob_str_dict[lib].append(glob_str)

        LookupSingular._process_config_opt_lib(
            config, "glob_extern_deps", add_to_glob_str_dict, top_lib=top_lib
        )

        for lib, glob_str_list in glob_str_dict.items():
            loc_rel_list = process_glob_patterns(glob_str_list, work_dir)
            for loc_rel in loc_rel_list:
                loc = path_from_dir(work_dir, loc_rel).resolve()
                extern_deps_list.append((lib, loc))

        return extern_deps_list

    def register_extern_deps_list(self, extern_deps_list):
        self.hash_extern_deps_list = hash(frozenset(extern_deps_list))
        for lib, loc in extern_deps_list:
            f_obj = FileObj(loc=loc, lib=lib)
            entity_name = Name(lib, loc.stem)
            f_obj.entities.append(entity_name)
            self.entity_name_2_file_obj[entity_name] = f_obj
            self.loc_2_file_obj[loc] = f_obj

    def register_file_list(self, file_list):
        self.hash_file_list = hash(frozenset(file_list))
        for lib, loc in file_list:
            parse_vhdl_file(self, loc, lib=lib)

    @staticmethod
    def create_from_config_dict(config: dict, work_dir: Path, **kwargs):

        inst = LookupSingular()
        inst.initalise_from_config_dict(config, work_dir, **kwargs)
        return inst



    def add_package(self, name: Name, f_obj: FileObj):
        self._add_to_dict(self.package_name_2_file_obj, name, f_obj)

    def add_entity(self, name: Name, f_obj: FileObj):
        self._add_to_dict(self.entity_name_2_file_obj, name, f_obj)

    def add_loc(self, loc: Path, f_obj: FileObj):
        loc = loc.resolve()
        self._add_to_dict(self.loc_2_file_obj, loc, f_obj)

    def get_loc(self, loc: Path):
        loc = loc.resolve()
        return self.loc_2_file_obj[loc]

    def has_loc(self, loc: Path):
        loc = loc.resolve()
        return loc in self.loc_2_file_obj

    def get_package(self, name: Name, f_obj_required_by : Optional[FileObj]) -> Optional[FileObj]:
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

    def write_file_list(self, f_loc, lib : Optional[str] = None):
        file_list = self.get_file_list(lib=lib)
        with open(f_loc, 'w') as f:
            for f_obj in file_list:
                if lib is None:
                    f.write(f'{f_obj.lib}\t{f_obj.loc}\n')
                else:
                    f.write(str(f_obj.loc)+'\n')

class LookupMulti(LookupSingular):
    TOML_KEYS = ["sub"]

    def __init__(
            self, look_subs: list[LookupSingular]): #, file_list: list[tuple[str, Path]] = [] ):
        log.debug('LookupMulti::__init__')
        self.look_subs = look_subs
        super().__init__(allow_duplicates=False)
        self.f_obj_top = None
        self._compile_order = None

    @staticmethod
    def create_from_config_dict(
            config: dict, work_dir: Path, look_subs=[], **kwargs
    ):

        look = LookupMulti(look_subs)
        look.initalise_from_config_dict(config, work_dir, **kwargs)
        return look

    def register_file_list(self, file_list):
        self.hash_file_list = hash(frozenset(file_list))
        for lib, loc in file_list:
            f_obj = self._get_loc_from_common(loc)
            if f_obj is not None:
                assert f_obj.lib == lib
                f_obj.register_with_lookup(self)
            else:
                # not passed in common lookup pass in prj lookup
                f_obj = parse_vhdl_file(self, loc, lib=lib)

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

    def get_package(self, name: Name, f_obj_required_by : Optional[FileObj]) -> Optional[FileObj]:
        def cb(name: Name, f_obj_required_by : Optional[FileObj]):
            return LookupSingular.get_package(self, name, f_obj_required_by)

        call_back_func_arr = [cb] + [l.get_package for l in self.look_subs]
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

class LookupPrj(LookupMulti):
    TOML_KEYS = ["top_file", "top_entity"]

    def __init__(
            self, look_subs: list[LookupMulti]) : #, file_list: list[tuple[str, Path]] = [] ):
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
        if "top_file" in config:

            l = []

            def call_back_func(lib: str, loc_str: str):
                loc_str = work_dir / loc_str
                n = (lib, loc_str)
                if len(l) != 0:
                    raise Exception(f"only supports one top_file got {l[0]} and {n}")
                l.append(n)

            LookupSingular._process_config_opt_lib(config, "top_file", call_back_func, top_lib=top_lib)

            assert len(l) == 1
            
            lib = l[0][0]
            loc = Path(l[0][1])
            look.set_top_file(loc, lib)

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

    def set_top_file(self, loc: Path, lib=None):
        self.f_obj_top = self.get_loc(loc, lib_to_add_to_if_not_found=lib)
        self._compile_order = None

    def set_top_entity(self, name, do_not_replace_top_file=True):
        if do_not_replace_top_file and self.f_obj_top is not None:
            f_obj = self.get_entity(name, f_obj_required_by=None)
            if f_obj != self.f_obj_top:
                raise RuntimeError(f'cound not find entity {top_ent_name} in file {loc}')

        else:
            f_obj = self.get_entity(name, f_obj_required_by=None)
            log.info(f'top_entity {name} found in file {f_obj.loc}')
            self.set_top_file(f_obj.loc, f_obj.lib)

    def has_top_file(self) -> bool:
        return self.f_obj_top is not None

    @property
    def compile_order(self):
        if self._compile_order is None:
            if self.f_obj_top is None:
                raise Exception(
                    "top_file must be declared in config or on command line"
                )

            self._compile_order = self.f_obj_top.get_compile_order(look)
        return self._compile_order

    def print_compile_order(self):
        print("compile order:")
        for f_obj in self.compile_order:
            print(f'\t{"|---"*f_obj.level}{f_obj.lib}:{f_obj.loc}')

    def write_compile_order(self, compile_order_loc: Path):
        with open(compile_order_loc, "w") as f_order:
            for f_obj in self.compile_order:
                f_order.write(f"{f_obj.lib} {f_obj.loc}\n")

    def write_compile_order_lib(self, compile_order_loc: Path, lib:str):
        lines = 0
        with open(compile_order_loc, "w") as f_order:
            for f_obj in self.compile_order:
                if lib == f_obj.lib:
                    f_order.write(f"{f_obj.loc}\n")
                    lines += 1
        if lines == 0:
            log.warning(f'not files found for libarary {lib}')

# Function to find matches in the VHDL code
def parse_vhdl_file(look: Optional[Lookup], loc: Path, lib="work"):

    log.info(f"passing VHDL file {loc}:")
    with open(loc, "r") as file:
        vhdl = file.read()

        f_obj = FileObj(loc, lib=lib)

        matches = {}
        for key, pattern in regex_patterns.items():
            matches[key] = pattern.findall(vhdl)
        for construct, found in matches.items():
            match construct:
                case "package_decl":
                    for item in found:
                        name = Name(lib, item)
                        f_obj.packages.append(name)
                        log.info(f"\tpackage_decl: {name}")
                case "entity_decl":
                    for item in found:
                        name = Name(lib, item)
                        f_obj.entities.append(name)
                        log.info(f"\tentity_decl: {name}")
                case "component_decl":
                    for item in found:
                        component = item
                        log.info(f"\tcomponent_decl: {component}")
                        f_obj.component_decl.append(component)
                case "component_inst":
                    for item in found:
                        component = item[1]
                        f_obj.component_deps.append(component)
                        log.info(f"\tcomponent_inst: {component}")  # Extract component name
                case "direct_inst":
                    for item in found:
                        l = item[1]
                        if l == 'work':
                            l = lib
                        name = Name(l, item[2])
                        f_obj.entity_deps.append(name)
                        log.info(
                                f"\tdirect_inst {name}"
                            )  # Extract library and component names
                case "package_use":
                    for item in found:
                        l = item[0]
                        if l == 'work':
                            l = lib
                        name = Name(l, item[1])
                        f_obj.package_deps.append(name)
                        log.info(
                            f"\tpackage_use {name}"
                        )  # Extract library and package names`
                case _:
                    raise Exception(f"error construct '{construct}'")

        if look is not None:
            f_obj.register_with_lookup(look)
        return f_obj


def contains_any(a: list, b: list) -> bool:
    for aa in a:
        if aa in b:
            return True
    return False


def issue_key(good_keys: list, keys: list) -> Optional[str]:
    for k in keys:
        if not k in good_keys:
            return k
    return None


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
            raise Exception(f'{toml_loc} expected suffix .toml or .json but got {toml_lox.suffix}')
        
    if not toml_loc.is_file():
        if toml_loc.is_absolute() or work_dir is None:
            raise FileNotFoundError(f"ERROR could not find file {toml_loc}")
        log.info(f"tring to find {toml_loc} in previouse directoires")
        temp_dir = work_dir.resolve()
        test = temp_dir / toml_loc
        while not test.is_file():
            print(f'temp_dir {temp_dir}')
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
        print(f'pre_cmds')
        for cmd in make_list(config['pre_cmds']):
            print(f'cmd {cmd}')
            subprocess.check_output(cmd, shell=True, cwd=work_dir)

    file_list = None
    extern_deps_list = None
    if attemp_read_pickle:
        inst, file_list, extern_deps_list = LookupSingular.atempt_to_load_from_pickle(pickle_loc, toml_loc, top_lib=top_lib)
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
            config, work_dir=work_dir, look_subs=look_subs, top_lib=top_lib, file_list=file_list, extern_deps_list = extern_deps_list
        )

    elif contains_any(config.keys(), LookupMulti.TOML_KEYS):

        log.info(f"create LookupMulti from {toml_loc}")
        inst = LookupMulti.create_from_config_dict(
            config, work_dir=work_dir, look_subs=look_subs, top_lib=top_lib, file_list=file_list, extern_deps_list = extern_deps_list
        )

    else :
        inst = LookupSingular.create_from_config_dict(
            config, work_dir=work_dir, top_lib=top_lib, file_list=file_list, extern_deps_list = extern_deps_list
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


# Use match statement to handle different constructs

def extract_lib_compiler_order(s)-> tuple[str, str]:
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VHDL dependency parser")

    parser.add_argument(
        "-v", "--verbose", action="count", help="verbose level... repeat up to two times"
    )
    parser.add_argument("-c", "--clear-pickle", action="store_true", help="Delete pickle cache files first.")
    parser.add_argument("--no-pickle", action="store_true", help="No not write or read any pickle caches") 
    parser.add_argument(
        "config_file",
        nargs="+",  # Allows one or more files
        type=str,
        help="Paths to / File Names of, the config TOML input file(s).",
    )
    parser.add_argument("--top-file", type=str, help="top level file to use")
    parser.add_argument("--top-entity", type=str, help="top entity to use")
    parser.add_argument("--top-lib", type=str, help="top level library")
    parser.add_argument(
        "--compile-order", type=str, help="Path to the compile order output file."
    )
    parser.add_argument(
        "--file-list", type=str, help="Output full file list of in project"
    )
    parser.add_argument(
        "--compile-order-lib", nargs ="+", type=extract_lib_compiler_order, help="expects 'lib:file' where 'file' is location to write the compile order of libary 'lib'."
    )
    parser.add_argument(
        "--file-list-lib", nargs ="+", type=extract_lib_compiler_order, help="expects 'lib:file' where 'file' is location to write the file list of library 'lib'."
    )

    args = parser.parse_args()

    set_log_level_from_verbose(args)

    work_dir=Path('.')
    top_lib = None
    if args.top_lib:
        top_lib = args.top_lib

    attemp_read_pickle = not args.clear_pickle and not args.no_pickle
    write_pickle = not args.no_pickle
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

    if args.top_file:
        look.set_top_file(Path(args.top_file), "work")

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

    if args.file_list_lib is not None:
        for lib, f in args.compile_order_lib:
            look.write_file_list(Path(f), lib)

    if args.compile_order is not None:
        look.write_compile_order(Path(args.compile_order))
    if args.compile_order_lib is not None:
        for lib, f in args.compile_order_lib:
            look.write_compile_order_lib(Path(f), lib)
            

