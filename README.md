# `hdldepends`
Simple python script to find VHDL file dependencies. I intend to cover Verilog as well at a latter date

# Install
Currently there is no install. This is something I may add later. The whole program is contained within one python script. Dependency to run the script is Python >=3.11

# Configuration files
Contain the project information include which files are include and from which libraries. These can be written in json or toml.

## Options tags
This is a list of all the allowed flags for the configuration files

For tags that accept a *library* dictionary, then the dictionary key is the library name. The dictionary value can be a list to contain more then one item to connect to the library. If no dictionary is not specified then the default `work` library is assumed.

### `glob_files`
Glob for files in the directory structure. Globs are run in order, place a '!' as the frist character to remove matching files from the list. (works similar to gitignore)

This tag accepts a *library* dictionary list or single value.

Examples:
 * "*.vhd",          # Include all VHDL files
 * "src/**/*.vhd",   # Include all VHDL files in src directory and subdirectories
 * "!src/temp/*",    # Exclude everything in the temp directory
 * "!**/*_test.py"   # Exclude all test files

### `pre_cmds`
Pre-commands are commands to run before other tags are processed.

This tag accepts a list or a single value

The major purpose of this is to automatically update files referenced by tag `file_list_files`. An example of `pre_cmds` could be.
```
git ls_files ./fw | grep ".vhd$" > fw_files_work.txt
```
This will place all `.vhd` files paths into fw-files_work.txt.


### `file_list_files`
File list of files is a tag which points to file containing a list of file paths to add to the project.

This tag accepts a *library* dictionary list or single value.

### `files`
Files contain files to add the project;

This tag accepts a *library* dictionary list or single value.

### `glob_extern_deps`
Glob for external dependencies in the directory structure. See `glob_files` and `extern_deps_file`

This tag accepts a *library* dictionary list or single value.

### `extern_deps_file`
External dependencies file is a tag which points to a file containing a list of files which are dependencies but not something which can be passed.

NOTE: There is an assumption that the name of file containing the external dependency (excluding the file extension) is the same as the entity name. 

NOTE: It is assumed that these external dependencies do not have other dependencies.

This tag accepts a *library* dictionary list or single value.


### `ignore_libs`
Ignore libraries tag indicates libraries which the design will ignore not add to the compile order.

This tag accepts a list or single value.

### `ignore_packages`
Ignore packages tag indicates packages which the design will ignore not add to the compile order.

This tag accepts a *library* dictionary list or single value.

### `ignore_entities`
Ignore entities tag indicates entities which the design will ignore not add to the compile order.

This tag accepts a *library* dictionary list or single value.

### `ignore_components`
Ignore components tag indicates components which the design will ignore not add to the compile order.

NOTE: you do not indicate which library the component comes from.

This tag accepts a list or single value.

### `package_file_skip_order`
Package file skip order tag added the package to the project but will ignore the package and all components in the package when creating the compile order. 

This tag accepts a *library* dictionary list or single value.

### `sub`
The sub tag adds other configuration files to the project. Which will be searched after the current configuration file. This can be a path relative to the directory containing this file or a file name contained in a parent directory of this file.

This tag accepts a list or a single value.

### `top_file`
This is the top level file to create the compile order from, it expects a path to the file not just the file name. You can use the command line option instead. Note, a configuration file containing this tag cannot be referenced by another configuration through the `sub` tag.

This tag accepts a single value.

### `top_entity`
This is the top entity to create the compile order from. You can use the command line option instead. Note, a configuration file containing this tag cannot be referenced by another configuration through the `sub` tag.

This tag accepts a single value.

# Command line
Below are the command line options for the `hdldepnds.py` command line program

## Options
Command line flag options

### `-h` `--help`
Print help message and exit

### `-v` `--verbose`
Selected the verbose level. 
 * Nothing is *warning*
 * `-v` is *info*, and
 * `-vv` is *debug*.

### `-c` `--clear-pickle`
Do not load anything from a pickle cache

### `--no-pickle`
Do not load anything from a pickle cache and do not write any pickle caches

### `--top-file`
The top file command line option specifies the project's top level file to create the compile order from. This works the same as the configuration file key `top_file`.

### `--top-entity`
The top file command line option specifies the project's top level file to create the compile order from. This works the same as the configuration file key `top_entity`.

### `--top-lib`
This is a bit of a hack. It will give the `work` library the passed name.

NOTE: If it changes it will evaluate every cached file referenced.

### `--file-list`
The file list command line option accepts a location to a file not yet created. This will save a list of all added to the hdldepends project. Each line contains:
 * library, and
 * absolute path to file under question.

### `--file-list-lib`
The file list library option exports the file list for one particular library. The option accepts *lib:file* where lib is the library to export and file is the location to export the file list to. Each line of the created file will contain the absolute path to a file.

### `--compile-order`
The compile order command line option accepts a location to a file not yet created. The project compile order will be exported to this file. Each line containing:
 * library, and
 * absolute path to file under question.

### `--compile-order-lib`
The compile order library option exports the compile order for one particular library. The option accepts *lib:file* where lib is the library to export and file is the location to export the compile order. Each line of the created file will contain the absolute path to a file.
 
## Positional Arguments
This program has only one positional argument.

### `config_file`
This can be a direct path to the project configuration file or just the file name. If only the file name is specified the program will look in parent directories for the file.

More then one configuration file can be specified. If more then one file is specified use the `--top-lib` command line option and not `top_file` configuration file key.
