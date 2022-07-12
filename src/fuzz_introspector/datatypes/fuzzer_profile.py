# Copyright 2022 Fuzz Introspector Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Fuzzer profile"""

import os
import json
import logging

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

from fuzz_introspector import cfg_load
from fuzz_introspector import cov_load
from fuzz_introspector import utils
from fuzz_introspector.datatypes import function_profile
from fuzz_introspector.exceptions import DataLoaderError

logger = logging.getLogger(name=__name__)
logger.setLevel(logging.INFO)


class FuzzerProfile:
    """
    Class for storing information about a given Fuzzer.
    This class essentially holds data corresponding to the output of run of the LLVM
    plugin. That means, the output from the plugin for a single fuzzer.
    """
    def __init__(
        self,
        cfg_file: str,
        frontend_yaml: Dict[Any, Any],
        target_lang: str = "c-cpp"
    ) -> None:
        # Defaults
        self.binary_executable: str = ""
        self.file_targets: Dict[str, Set[str]] = dict()
        self.coverage: Optional[cov_load.CoverageProfile] = None
        self.all_class_functions: Dict[str, function_profile.FunctionProfile] = dict()

        self.target_lang = target_lang
        self.introspector_data_file = cfg_file

        # Load calltree file
        self.function_call_depths = cfg_load.data_file_read_calltree(cfg_file)

        # Read yaml data (as dictionary) from frontend
        try:
            self.fuzzer_source_file: str = frontend_yaml['Fuzzer filename']
        except KeyError:
            raise DataLoaderError("Fuzzer filename not in loaded yaml")
        self._set_function_list(frontend_yaml)

    def resolve_coverage_link(
        self,
        cov_url: str,
        source_file: str,
        lineno: int,
        function_name: str
    ) -> str:
        """Resolves a link to a coverage report."""
        if self.target_lang == "c-cpp":
            self._resolve_c_cpp_coverage_link(
                cov_url,
                source_file,
                lineno,
                function_name
            )
        elif self.target_lang == "python":
            self._resolve_python_coverage_link(
                cov_url,
                source_file,
                lineno,
                function_name
            )
        else:
            logger.info("Could not find any html_status.json file")
        return "#"

    def refine_paths(self, basefolder: str) -> None:
        """Iterate over source files in the calltree and file_targets and remove
        the fuzzer's basefolder from the path.

        The main point for doing this is clearing any prefixed path that may
        exist. This is, for example, the case in OSS-Fuzz projects where most
        files will be prefixed with /src/project_name.
        """
        # Only do this if basefolder is not wrong
        if basefolder == "/":
            return

        # TODO (David): this is an over-approximation? We should not replace all throughout,
        # but only the start of the string.
        self.fuzzer_source_file = self.fuzzer_source_file.replace(basefolder, "")

        if self.function_call_depths is not None:
            all_callsites = cfg_load.extract_all_callsites(self.function_call_depths)
            for cs in all_callsites:
                cs.dst_function_source_file = cs.dst_function_source_file.replace(basefolder, "")

            new_dict = {}
            for key in self.file_targets:
                new_dict[key.replace(basefolder, "")] = self.file_targets[key]
            self.file_targets = new_dict

    def reaches_file(
        self,
        file_name: str,
        basefolder: Optional[str] = None
    ) -> bool:
        if file_name in self.file_targets:
            return True

        # Only some file paths have removed base folder. We must check for
        # both if basefolder is set.
        if basefolder is not None:
            return file_name.replace(basefolder, "") in self.file_targets
        return False

    def reaches_func(self, func_name: str) -> bool:
        return func_name in self.functions_reached_by_fuzzer

    def correlate_executable_name(self, correlation_dict) -> None:
        for elem in correlation_dict['pairings']:
            if os.path.basename(self.introspector_data_file) in f"{elem['fuzzer_log_file']}.data":
                self.binary_executable = str(elem['executable_path'])

                lval = os.path.basename(self.introspector_data_file)
                rval = f"{elem['fuzzer_log_file']}.data"
                logger.info(f"Correlated {lval} with {rval}")

    def get_key(self) -> str:
        """Returns the "key" we use to identify this Fuzzer profile."""
        if self.binary_executable != "":
            return os.path.basename(self.binary_executable)

        return self.fuzzer_source_file

    def accummulate_profile(self, target_folder: str) -> None:
        """Triggers various analyses on the data of the fuzzer. This is used
        after a profile has been initialised to generate more interesting data.
        """
        self._set_all_reached_functions()
        self._set_all_unreached_functions()
        self._load_coverage(target_folder)
        self._set_file_targets()
        self._set_total_basic_blocks()
        self._set_total_cyclomatic_complexity()

    def get_cov_uncovered_reachable_funcs(self) -> List[str]:
        """Gets all functions that are statically reachable but are not
        covered by runtime coverage.

        Returns:
            List with names of all the functions that are reachable but not
            covered.
            If there is no coverage information returns empty list.
        """
        if self.coverage is None:
            return []

        uncovered_funcs = []
        for funcname in self.functions_reached_by_fuzzer:
            total_func_lines, hit_lines, hit_percentage = self.get_cov_metrics(funcname)
            if total_func_lines is None:
                uncovered_funcs.append(funcname)
                continue
            if hit_lines == 0:
                uncovered_funcs.append(funcname)
        return uncovered_funcs

    def is_file_covered(
        self,
        file_name: str,
        basefolder: Optional[str] = None
    ) -> bool:
        # We need to refine the pathname to match how coverage file paths are.
        file_name = os.path.abspath(file_name)

        # Refine filename if needed
        if basefolder is not None and basefolder != "/":
            new_file_name = file_name.replace(basefolder, "")
        else:
            new_file_name = file_name

        for funcname in self.all_class_functions:
            # Check it's a relevant filename
            func_file_name = self.all_class_functions[funcname].function_source_file
            if basefolder is not None and basefolder != "/":
                new_func_file_name = func_file_name.replace(basefolder, "")
            else:
                new_func_file_name = func_file_name
            if func_file_name != file_name and new_func_file_name != new_file_name:
                continue
            # Return true if the function is hit
            tf, hl, hp = self.get_cov_metrics(funcname)
            if hp is not None and hp > 0.0:
                if func_file_name in self.file_targets or new_file_name in self.file_targets:
                    return True
        return False

    def get_cov_metrics(
        self,
        funcname: str
    ) -> Tuple[Optional[int], Optional[int], Optional[float]]:
        if self.coverage is None:
            return None, None, None
        try:
            total_func_lines, hit_lines = self.coverage.get_hit_summary(funcname)
            if total_func_lines is None or hit_lines is None:
                return None, None, None

            hit_percentage = (hit_lines / total_func_lines) * 100.0
            return total_func_lines, hit_lines, hit_percentage
        except Exception:
            return None, None, None

    def write_stats_to_summary_file(self) -> None:
        file_target_count = len(self.file_targets) if self.file_targets is not None else 0
        utils.write_to_summary_file(
            self.get_key(),
            "stats",
            {
                "total-basic-blocks": self.total_basic_blocks,
                "total-cyclomatic-complexity": self.total_cyclomatic_complexity,
                "file-target-count": file_target_count,
            }
        )

    def _set_all_reached_functions(self) -> None:
        """Sets self.functions_reached_by_fuzzer to all functions reached by
        the fuzzer. This is based on identifying all functions reached by the
        fuzzer entrypoint function, e.g. LLVMFuzzerTestOneInput in C/C++.
        """
        if "LLVMFuzzerTestOneInput" in self.all_class_functions:
            self.functions_reached_by_fuzzer = (
                self.all_class_functions["LLVMFuzzerTestOneInput"].functions_reached
            )
            return

        # Find Python entrypoint
        for func_name in self.all_class_functions:
            if "TestOneInput" in func_name:
                reached = self.all_class_functions[func_name].functions_reached
                self.functions_reached_by_fuzzer = reached
                return

        # TODO: make fuzz-introspector exceptions
        raise Exception

    def _set_all_unreached_functions(self) -> None:
        """Sets self.functions_unreached_by_fuzzer to all functions that are
        statically unreached. This is computed as the set difference between
        self.all_class_functions and self.functions_reached_by_fuzzer.
        """
        self.functions_unreached_by_fuzzer = [
            f.function_name for f
            in self.all_class_functions.values()
            if f.function_name not in self.functions_reached_by_fuzzer
        ]

    def _load_coverage(self, target_folder: str) -> None:
        """Load coverage data for this profile"""
        logger.info(f"Loading coverage of type {self.target_lang}")
        if self.target_lang == "c-cpp":
            self.coverage = cov_load.llvm_cov_load(
                target_folder,
                self._get_target_fuzzer_filename()
            )
        elif self.target_lang == "python":
            self.coverage = cov_load.load_python_json_cov(
                target_folder
            )
        else:
            raise DataLoaderError(
                "The profile target has no coverage loading support"
            )

    def _get_target_fuzzer_filename(self) -> str:
        return self.fuzzer_source_file.split("/")[-1].replace(".cpp", "").replace(".c", "")

    def _set_file_targets(self) -> None:
        """Sets self.file_targets to be a dictionarty of string to string.
        Each key in the dictionary is a filename and the corresponding value is
        a set of strings containing strings which are the names of the functions
        in the given file that are reached by the fuzzer.
        """
        if self.function_call_depths is not None:
            all_callsites = cfg_load.extract_all_callsites(self.function_call_depths)
            for cs in all_callsites:
                if cs.dst_function_source_file.replace(" ", "") == "":
                    continue
                if cs.dst_function_source_file not in self.file_targets:
                    self.file_targets[cs.dst_function_source_file] = set()
                self.file_targets[cs.dst_function_source_file].add(cs.dst_function_name)

    def _set_total_basic_blocks(self) -> None:
        """Sets self.total_basic_blocks to the sum of basic blocks of all the
        functions reached by this fuzzer.
        """
        total_basic_blocks = 0
        for func in self.functions_reached_by_fuzzer:
            fd = self.all_class_functions[func]
            total_basic_blocks += fd.bb_count
        self.total_basic_blocks = total_basic_blocks

    def _set_total_cyclomatic_complexity(self) -> None:
        """Sets self.total_cyclomatic_complexity to the sum of cyclomatic
        complexity of all functions reached by this fuzzer.
        """
        self.total_cyclomatic_complexity = 0
        for func in self.functions_reached_by_fuzzer:
            fd = self.all_class_functions[func]
            self.total_cyclomatic_complexity += fd.cyclomatic_complexity

    def _set_function_list(self, frontend_yaml: Dict[Any, Any]) -> None:
        """Read all function field from yaml data dictionary into
        instances of FunctionProfile
        """
        for elem in frontend_yaml['All functions']['Elements']:
            if self._is_func_name_missing_normalisation(elem['functionName']):
                logger.info(
                    f"May have non-normalised function: {elem['functionName']}"
                )

            func_profile = function_profile.FunctionProfile(elem)
            logger.debug(f"Adding {func_profile.function_name}")
            self.all_class_functions[func_profile.function_name] = func_profile

    def _is_func_name_missing_normalisation(self, func_name: str) -> bool:
        if "." in func_name:
            split_name = func_name.split(".")
            if split_name[-1].isnumeric():
                return True
        return False

    def _resolve_c_cpp_coverage_link(
        self,
        cov_url: str,
        source_file: str,
        lineno: int,
        function_name: str
    ) -> str:
        """Resolves link to HTML coverage report for C/CPP targets"""
        return cov_url + source_file + ".html#L" + str(lineno)

    def _resolve_python_coverage_link(
        self,
        cov_url: str,
        source_file: str,
        lineno: int,
        function_name: str
    ) -> str:
        """Resolves link to HTML coverage report for Python targets"""
        # Temporarily for debugging purposes. TODO: David remove this later
        # Find the html_status.json file. This is a file generated by the Python
        # coverate utility and contains mappings from source to html file. We
        # need this mapping in order to create links from the data extracted
        # during AST analysis, as there we only have the source code.
        html_summaries = utils.get_all_files_in_tree_with_regex(".", ".*html_status.json$")
        logger.info(str(html_summaries))
        if len(html_summaries) > 0:
            html_idx = html_summaries[0]
            with open(html_idx, "r") as jf:
                data = json.load(jf)
            for fl in data['files']:
                found_target = utils.approximate_python_coverage_files(
                    function_name,
                    data['files'][fl]['index']['relative_filename'],
                )
                if found_target:
                    return cov_url + "/" + fl + ".html" + "#t" + str(lineno)
        else:
            logger.info("Could not find any html_status.json file")
        return "#"
