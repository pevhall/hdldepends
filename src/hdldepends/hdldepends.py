import re
import sys
import pickle

# try:
import tomllib
# except ModuleNotFoundError:
#     import pip._vendor.tomli as tomllib
import argparse
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
        r"^(?!\s*--)\s*package\s+(\w+)\s+is.*?end\s+package",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "entity_decl": re.compile(
        r"^(?!\s*--)\s*entity\s+(\w+)\s+is.*?end\s+entity",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    ),
    "component_decl": re.compile(
        r"^(?!\s*--)\s*component\s+(\w+)\s+is.*?end\s+component",
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

class Name:
    lib: str
    name: Optional[str]

    def __init__(self, lib, name):
        self.lib = lib.lower() #VHDL case insenstive
        if name is not None:
            self.name = name.lower() #VHDL case insenstive
        else:
            self.name = None

    def __str__(self):
        return f"{self.lib}.{self.name}"

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


def get_file_modification_time(f: Path):
    return f.lstat().st_mtime



def str_to_name(s: str):
    l = s.split(".")
    if len(l) == 1:  # no lib use default
        return Name("work", name=l[0])
    elif len(l) == 2:
        return Name(lib=l[0], name=l[1])
    else:
        raise Exception(f"ERROR converting str {s} to Name")


class Lookup:
    def get_package(self, name: Name):
        pass

    def get_entity(self, name: Name):
        pass

    def add_loc(self, loc: Path, f_obj: "FileObj"):
        pass


class FileObj:

    def __init__(self, loc: Path, lib: str):
        self.loc = loc.resolve()
        self.lib = lib
        self.packages: list[Name] = []
        self.entities: list[Name] = []
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

    def get_file_deps(self, look: Lookup):
        file_deps = []

        for p in self.package_deps:
            f_obj = look.get_package(p)
            if f_obj is not None:
                self._add_to_f_deps(file_deps, f_obj)

        for e in self.entity_deps:
            f_obj = look.get_entity(e)
            if f_obj is not None:
                self._add_to_f_deps(file_deps, f_obj)

        return file_deps

    def get_compile_order(self, look: Lookup) -> list["FileObj"]:
        return self._get_compile_order(look)

    def _get_compile_order(
        self, look: Lookup, files_passed=[], level=0
    ) -> list["FileObj"]:
        files_passed.append(self)
        order: list["FileObj"] = []
        for f_obj in self.get_file_deps(look):
            if f_obj not in files_passed:
                order += f_obj._get_compile_order(look, files_passed, level + 1)
        order.append(self)
        self.level = level
        return order

    def requires_update(self):
        return self.get_modification_time_on_disk() != self.modification_time

    def update(self) -> tuple[bool, bool]:
        """Returns True if the dependencies have changed, Returns True if file was modified"""
        if self.requires_update():
            f_obj = parse_vhdl_file(None, self.loc, self.lib)
            if self == f_obj:
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


    def __eq__(self, other : "FileObj"):
        return (self.loc      == other.loc
            and self.lib      == other.lib
            and self.packages == other.packages
            and self.entities == other.entities
            and self.package_deps == other.package_deps
            and self.entity_deps == other.entity_deps)
            #modificaiton time and level are not checked

        if self.lib != self.lib:
            return False
        if self.lib != self.lib:
            return False



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


class LookupCommon(Lookup):
    TOML_KEYS = [
        "ignore_libs",
        "ignore_packages",
        "ignore_entities",
        "files",
        "file_list_files",
    ]

    def __init__(self, allow_duplicates: bool = True):
        self.allow_duplicates = allow_duplicates
        self.package_name_2_file_obj: dict[Name, FileObjLookup] = {}
        self.entity_name_2_file_obj: dict[Name, FileObjLookup] = {}
        self.loc_2_file_obj: dict[Path, FileObjLookup] = {}
        self.ignore_set_libs: set[str] = set()
        self.ignore_set_packages: set[Name] = set()
        self.ignore_set_entities: set[Name] = set()
        self.toml_loc: Optional[Path] = None
        self.toml_modification_time = None

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
            pickle_loc: Path, toml_loc: Path
    ) -> Optional[object]:
        assert toml_loc.is_file()
        if pickle_loc.is_file():
            log.info(f"atempting to load cache from {pickle_loc}")
            pickle_mod_time = get_file_modification_time(pickle_loc)
            with open(pickle_loc, "rb") as pickle_f:
                inst = pickle.load(pickle_f)
            # time_diff = pickle_mod_time - inst.toml_modification_time

            toml_modification_time = get_file_modification_time(toml_loc)
            if toml_modification_time == inst.toml_modification_time:
                log.info(f"loaded from {pickle_loc}, updating required files")
                any_changes = inst.check_for_src_files_updates()
                if any_changes:
                    log.info(f"Updating pickle wtih the changes detected on disk")
                    inst.save_to_pickle(pickle_loc)
        
                return inst
            log.info(f"{pickle_loc} out of date")
        return None

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
    def _process_config_opt_lib(config: dict, key: str, callback):
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
                callback("work", v)
        else:
            callback("work", c_val)

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
        config: dict, key: str
    ) -> set[Name]:
        l = []

        def call_back_func(lib: str, name: str):
            l.append(Name(lib=lib, name=name))

        LookupCommon._process_config_opt_lib(config, key, call_back_func)
        log.info(f"{key} = {l}")
        return set(l)

    def initalise_from_config_dict(self, config: dict):
        self.ignore_set_libs = LookupCommon.extract_set_str_from_config(
            config, "ignore_libs"
        )
        self.ignore_set_packages = LookupCommon.extract_set_name_from_config(
            config, "ignore_packages"
        )
        self.ignore_set_entities = LookupCommon.extract_set_name_from_config(
            config, "ignore_entities"
        )

    @staticmethod
    def get_file_list_from_config_dict(config: dict, work_dir: Path):

        file_list: list[tuple(str, Path)] = []

        def add_file_to_list(lib, loc_str):
            loc = path_from_dir(work_dir, Path(loc_str))
            file_list.append((lib, loc))

        LookupCommon._process_config_opt_lib(config, "files", add_file_to_list)

        def add_file_list_to_list(lib, str_list_file):
            loc_list_file = Path(str_list_file)
            loc_list_file = path_from_dir(work_dir, loc_list_file)
            with open(loc_list_file, "r") as f_list_file:
                for loc_str in f_list_file:
                    loc_str = loc_str.strip()
                    loc = path_from_dir(loc_list_file.parents[0], Path(loc_str))
                    file_list.append((lib, loc))

        LookupCommon._process_config_opt_lib(
            config, "file_list_files", add_file_list_to_list
        )

        return file_list

    @staticmethod
    def create_from_config_dict(config: dict, work_dir: Path):

        inst = LookupCommon()
        inst.initalise_from_config_dict(config)
        file_list = LookupCommon.get_file_list_from_config_dict(
            config, work_dir
        )

        for lib, loc in file_list:
            parse_vhdl_file(inst, loc, lib=lib)

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

    def get_package(self, name: Name) -> Optional[FileObj]:
        if name not in self.package_name_2_file_obj:
            if name.lib in self.ignore_set_libs:
                return None
            if name in self.ignore_set_packages:
                return None
            raise KeyError(f"ERROR: Could not find package {name}")

        item = self.package_name_2_file_obj[name]
        if isinstance(item, FileObj):
            return item
        elif isinstance(item, ConflictFileObj):
            item.log_confict(name)
            raise KeyError(f"ERROR: confict on package {name}")

    def get_entity(self, name: Name) -> Optional[FileObj]:
        if name not in self.entity_name_2_file_obj:
            if name.lib in self.ignore_set_libs:
                return None

            if name in self.ignore_set_entities:
                return None
            raise KeyError(f"ERROR: Could not find entity {name}")

        item = self.entity_name_2_file_obj[name]
        if isinstance(item, FileObj):
            return item
        elif isinstance(item, ConflictFileObj):
            item.log_confict(name)
            raise KeyError(f"ERROR: confict on entity {name}")


class LookupPrj(LookupCommon):
    TOML_KEYS = ["common_toml", "top_file"]

    def __init__(
        self, look_common: list[LookupCommon], file_list: list[tuple[str, Path]] = []
    ):
        self.look_common = look_common
        super().__init__(allow_duplicates=False)
        self.register_file_list(file_list)
        self.f_obj_top = None
        self._compile_order = None

    @staticmethod
    def create_from_config_dict(
        config: dict, work_dir: Path, look_common=[]
    ):

        look = LookupPrj(look_common)
        look.initalise_from_config_dict(config)
        file_list = LookupCommon.get_file_list_from_config_dict(
            config, work_dir
        )

        look.register_file_list(file_list)
        if "top_file" in config:

            l = []

            def call_back_func(lib: str, loc_str: str):
                n = (lib, loc_str)
                if len(l) != 0:
                    raise Exception(f"only supports one top_file got {l[0]} and {n}")
                l.append(n)

            LookupCommon._process_config_opt_lib(config, "top_file", call_back_func)

            assert len(l) == 1

            lib = l[0][0]
            loc = Path(l[0][1])
            look.set_top_file(loc, lib)

        return look

    def set_top_file(self, loc: Path, lib=None):
        self.f_obj_top = self.get_loc(loc, lib_to_add_to_if_not_found=lib)
        self._compile_order = None

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
            print(f'\t{"|---"*f_obj.level}{f_obj.loc}')

    def write_compile_order(self, compile_order_loc: Path):
        with open(compile_order_loc, "w") as f_order:
            for f_obj in self.compile_order:
                f_order.write(f"{f_obj.lib} {f_obj.loc}\n")

    def register_file_list(
        self, file_list: list[tuple[str, Path]]
    ):
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
        for l_common in self.look_common:
            if l_common.has_loc(loc):
                return l_common.get_loc(loc)
        return None

    def _get_named_item(
        self, item_ref: str, name: Name, call_back_func_arr
    ) -> Optional[FileObj]:
        for call_back in call_back_func_arr:
            try:
                result = call_back(name)
                return result
            except KeyError:
                pass

        raise KeyError(f"{item_ref} {name} not found in depndency lookups")

    def get_package(self, name: Name) -> Optional[FileObj]:
        def cb(name: Name):
            return LookupCommon.get_package(self, name)

        call_back_func_arr = [cb] + [l.get_package for l in self.look_common]
        return self._get_named_item("package", name, call_back_func_arr)

    def get_entity(self, name: Name) -> Optional[FileObj]:
        def cb(name: Name):
            return LookupCommon.get_entity(self, name)

        call_back_func_arr = [cb] + [l.get_entity for l in self.look_common]
        return self._get_named_item("entity", name, call_back_func_arr)


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
                        log.info(f"\tcomponent_decl: {name}")
                case "component_inst":
                    for item in found:
                        name = Name(lib, item[1])
                        f_obj.entity_deps.append(name)
                        log.info(f"\tcomponent_inst: {name}")  # Extract component name
                case "direct_inst":
                    for item in found:
                        name = Name(item[1], item[2])
                        f_obj.entity_deps.append(name)
                        log.info(
                                f"\tdirect_inst {name}"
                            )  # Extract library and component names
                case "package_use":
                    for item in found:
                        name = Name(item[0], item[1])
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


def create_lookup_from_toml(
    toml_loc: Path, work_dir: Optional[Path] = None
):
    if not toml_loc.is_file():
        if toml_loc.is_absolute() or work_dir is None:
            raise FileNotFoundError(f"ERROR could not find file {toml_loc}")
        log.info(f"tring to find {toml_loc} in previouse directoires")
        temp_dir = work_dir
        test = temp_dir / toml_loc
        while not test.is_file():
            temp_dir = temp_dir.parents[0]
            test = temp_dir / toml_loc
            if test == Path("/"):
                raise FileNotFoundError(f"ERROR could not find file {toml_loc}")
        toml_loc = test
    with open(toml_loc, "rb") as toml_f:
        config = tomllib.load(toml_f)
    work_dir = toml_loc.parents[0]
    picke_loc = LookupCommon.toml_loc_to_pickle_loc(toml_loc)

    error_key = issue_key(LookupPrj.TOML_KEYS + LookupCommon.TOML_KEYS, config.keys())
    if error_key is not None:
        raise KeyError(f"Got unexpected key {error_key} in file {toml_loc}")

    work_dir = toml_loc.parents[0]

    if contains_any(config.keys(), LookupPrj.TOML_KEYS):
        look_common = []

        if "common_toml" in config:
            c_locs = config["common_toml"]
            c_locs = make_list(c_locs)
            for loc in c_locs:
                loc = Path(loc)
                look_common.append(
                    create_lookup_from_toml(loc, work_dir)
                )

        log.info(f"create LookupPrj from {toml_loc}")
        return LookupPrj.create_from_config_dict(
            config, work_dir=work_dir, look_common=look_common
        )
    log.info(f"create LookupCommon from {toml_loc}")
    pickle_loc = LookupCommon.toml_loc_to_pickle_loc(toml_loc)

    inst = LookupCommon.atempt_to_load_from_pickle(pickle_loc, toml_loc)
    if inst is not None:
        return inst

    log.info(f"loading from {toml_loc}")
    with open(toml_loc, "rb") as toml_f:
        config = tomllib.load(toml_f)
        inst = LookupCommon.create_from_config_dict(
            config, work_dir=work_dir
        )

    inst.toml_modification_time = get_file_modification_time(toml_loc)
    inst.save_to_pickle(pickle_loc)
    return inst


# Use match statement to handle different constructs


def set_log_level_from_verbose(args):
    global log_level
    if args.verbose is not None:
        log_level = args.verbose

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VHDL dependency parser")

    parser.add_argument(
        "-v", "--verbose", action="count", help="verbose level... repeat up to two times"
    )
    # parser.add_argument("-c", "--clear-cache", action="store_true", help="Delete pickle cache files first.") #TODO
    parser.add_argument(
        "config_toml",
        nargs="+",  # Allows one or more files
        type=str,
        help="Paths to / File Names of, the config TOML input file(s).",
    )
    parser.add_argument("--top-file", type=str, help="top level file to use")
    parser.add_argument(
        "--compile-order", type=str, help="Path to the compile order output file."
    )
    # parser.add_argument("-d", "--file-dependencies", type=str, help="Path to the file to print the immidiate dependencies for")

    args = parser.parse_args()

    set_log_level_from_verbose(args)

    # Example usage
    # print("Clear Cache:", args.clear_cache)
    log.debug("Config TOML:", args.config_toml)
    log.debug("Compile Order:", args.compile_order)
    # print("File Dependencies:", args.file_dependencies)

    if len(args.config_toml) == 1:
        look = create_lookup_from_toml(Path(args.config_toml[0]))
    else:
        look_common = []
        for c_toml in common_toml:
            look_common.append(
                create_lookup_from_toml(
                    Path(c_toml), work_dir=work_dir
                )
            )
        look = LookupPrj(look_common)

    if args.top_file:
        look.set_top_file(Path(args.top_file), "work")

    if look.has_top_file():
        look.print_compile_order()

    if args.compile_order is not None:
        look.write_compile_order(Path(args.compile_order))

