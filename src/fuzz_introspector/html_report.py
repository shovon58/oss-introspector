# Copyright 2021 Fuzz Introspector Authors
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
"""Module for creating HTML reports"""
import os
import logging
import json
import typing
import random
import string
from datetime import datetime

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

from fuzz_introspector import (analysis, cfg_load, constants, html_constants,
                               html_helpers, json_report, styling, utils)

from fuzz_introspector.datatypes import project_profile, fuzzer_profile

logger = logging.getLogger(name=__name__)


def create_horisontal_calltree_image(image_name: str,
                                     profile: fuzzer_profile.FuzzerProfile,
                                     dump_files: bool) -> List[str]:
    """
    Creates a horisontal image of the calltree. The height is fixed and
    each element on the x-axis shows a node in the calltree in the form
    of a rectangle. The rectangle is red if not visited and green if visited.
    """
    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ModuleNotFoundError:
        # It's useful to avoid this in CIFuzz because building the fuzzers with
        # matplotlib costs a lot of time (10 minutes) in the CI, which we prefer
        # to avoid.
        logger.info("Could not import matplotlib. No bitmaps are created")
        return []

    logger.info(f"Creating image {image_name}")

    if profile.fuzzer_callsite_calltree is None:
        return []

    # Extract color sequence
    color_list: List[str] = []
    for node in cfg_load.extract_all_callsites(
            profile.fuzzer_callsite_calltree):
        if (node.cov_color != ""):
            color_list.append(node.cov_color)
    logger.info(f"- extracted the callsites ({len(color_list)} nodes)")

    # Show one read rectangle if the list is empty. An alternative is
    # to not include the image at all.
    if len(color_list) == 0:
        color_list = ['red']
    plot_size = len(color_list)
    multiplier = plot_size / len(color_list)

    fig, ax = plt.subplots()
    ax.clear()
    fig.set_size_inches(15, 2.5)
    ax.plot()

    # Create our rectangles
    curr_start_x = 0.0
    curr_size = 1.0
    curr_color = color_list[0]
    height = 1.0

    for i in range(1, len(color_list)):
        if curr_color == color_list[i]:
            curr_size += 1.0
        else:
            final_start_x = curr_start_x * multiplier
            final_size = curr_size * multiplier
            ax.add_patch(
                Rectangle((final_start_x, 0.0),
                          final_size,
                          height,
                          color=curr_color))

            # Start next color area
            curr_start_x += curr_size
            curr_color = color_list[i]
            curr_size = 1.0
    logger.info("- iterated over color list")

    # Plot the last case
    final_start_x = curr_start_x * multiplier
    final_size = curr_size * multiplier
    ax.add_patch(
        Rectangle((final_start_x, 0.0), final_size, height, color=curr_color))
    ax.set_yticklabels([])
    ax.set_yticks([])
    xlabel = ax.set_xlabel("Callsite index")

    # Save the image
    if dump_files:
        logger.info("- saving image")
        plt.title(image_name.replace(".png", "").replace("_colormap", ""))
        fig.tight_layout()
        fig.savefig(image_name, bbox_extra_artists=[xlabel])
        logger.info("- image saved")
    return color_list


def create_overview_table(tables: List[str],
                          profiles: List[fuzzer_profile.FuzzerProfile]) -> str:
    """Table with an overview of all the fuzzers"""
    html_string = html_helpers.html_create_table_head(
        tables[-1], html_constants.FUZZER_OVERVIEW_TABLE_COLUMNS)
    for profile in profiles:  # create a row for each fuzzer.
        fuzzer_filename = profile.fuzzer_source_file
        html_string += html_helpers.html_table_add_row([
            profile.identifier, fuzzer_filename,
            len(profile.functions_reached_by_fuzzer),
            len(profile.functions_unreached_by_fuzzer),
            profile.max_func_call_depth,
            len(profile.file_targets), profile.total_basic_blocks,
            profile.total_cyclomatic_complexity,
            fuzzer_filename.replace(" ", "").split("/")[-1]
        ])
    html_string += ("\n</tbody></table>")
    return html_string


def create_all_function_table(
    tables: List[str],
    proj_profile: project_profile.MergedProjectProfile,
    coverage_url: str,
    basefolder: str,
    table_id: Optional[str] = None
) -> Tuple[str, List[typing.Dict[str, Any]], List[typing.Dict[str, Any]]]:
    """Table for all functions in the project. Contains many details about each
        function"""
    random_suffix = '_' + ''.join(
        random.choices(string.ascii_lowercase + string.ascii_uppercase, k=7))
    if table_id is None:
        table_id = tables[-1]

    html_string = html_helpers.html_create_table_head(
        table_id,
        html_constants.ALL_FUNCTION_TABLE_COLUMNS,
        sort_by_column=len(html_constants.ALL_FUNCTION_TABLE_COLUMNS) - 1,
        sort_order="desc")

    # an array in development to replace html generation in python.
    # this will be stored as a json object and will be used to populate
    # the table in the frontend
    table_rows_json_html = []
    table_rows_json_report = []

    for fd_k, fd in proj_profile.get_all_functions_with_source().items():
        demangled_func_name = utils.demangle_cpp_func(fd.function_name)
        try:
            func_total_lines, hit_lines = proj_profile.runtime_coverage.get_hit_summary(
                demangled_func_name)
            if hit_lines is None or func_total_lines is None:
                hit_percentage = 0.0
            else:
                hit_percentage = (hit_lines / func_total_lines) * 100.0
        except Exception:
            hit_percentage = 0.0

        func_cov_url = proj_profile.resolve_coverage_report_link(
            coverage_url, fd.function_source_file, fd.function_linenumber,
            fd.function_name)

        if proj_profile.runtime_coverage.is_func_hit(fd.function_name):
            func_hit_at_runtime_row = "yes"
        else:
            func_hit_at_runtime_row = "no"

        func_name_row = f"""<a href='{ func_cov_url }'><code class='language-clike'>
            { demangled_func_name }
            </code></a>"""

        collapsible_id = demangled_func_name + random_suffix

        if fd.hitcount > 0:
            reached_by_fuzzers_row = html_helpers.create_collapsible_element(
                str(fd.hitcount), str(fd.reached_by_fuzzers), collapsible_id)
        else:
            reached_by_fuzzers_row = "0"

        if fd.arg_count > 0:
            args_row = html_helpers.create_collapsible_element(
                str(fd.arg_count), str(fd.arg_types), collapsible_id + "2")
        else:
            args_row = "0"

        row_element = {
            "Func name": func_name_row,
            "func_url": func_cov_url,
            "Functions filename": fd.function_source_file,
            "Args": args_row,
            "Function call depth": fd.function_depth,
            "Reached by Fuzzers": reached_by_fuzzers_row,
            "collapsible_id": collapsible_id,
            "Fuzzers runtime hit": func_hit_at_runtime_row,
            "Func lines hit %": "%.5s" % (str(hit_percentage)) + "%",
            "I Count": fd.i_count,
            "BB Count": fd.bb_count,
            "Cyclomatic complexity": fd.cyclomatic_complexity,
            "Functions reached": len(fd.functions_reached),
            "Reached by functions": len(fd.incoming_references),
            "Accumulated cyclomatic complexity":
            fd.total_cyclomatic_complexity,
            "Undiscovered complexity": fd.new_unreached_complexity
        }
        table_rows_json_html.append(row_element)

        # Add the entry to json list.
        # Overwrite some fields to have raw text and not HTML-formatted text.
        json_copy = row_element.copy()
        json_copy['Func name'] = demangled_func_name
        json_copy['Args'] = str(fd.arg_types)
        json_copy['Reached by Fuzzers'] = fd.reached_by_fuzzers
        table_rows_json_report.append(json_copy)

    logger.info("Assembled a total of %d entries" %
                (len(table_rows_json_report)))
    html_string += ("</table>\n")
    return html_string, table_rows_json_html, table_rows_json_report


def create_boxed_top_summary_info(
        tables: List[str],
        proj_profile: project_profile.MergedProjectProfile,
        conclusions: List[html_helpers.HTMLConclusion],
        extract_conclusion: bool,
        display_coverage: bool = False) -> str:
    html_string = ""

    html_string += html_helpers.create_percentage_graph(
        "Functions statically reachable by fuzzers",
        proj_profile.reached_func_count, proj_profile.total_functions)

    html_string += html_helpers.create_percentage_graph(
        "Cyclomatic complexity statically reachable by fuzzers",
        proj_profile.reached_complexity, proj_profile.total_complexity)

    if display_coverage:
        covered_funcs = proj_profile.get_all_runtime_covered_functions()
        html_string += html_helpers.create_percentage_graph(
            "Runtime code coverage of functions", len(covered_funcs),
            proj_profile.total_functions)

    # Add conclusion
    if extract_conclusion:
        create_conclusions(conclusions, proj_profile.reached_func_percentage,
                           proj_profile.reached_complexity_percentage)
    return html_string


def create_conclusions(conclusions: List[html_helpers.HTMLConclusion],
                       reached_percentage: float,
                       reached_complexity_percentage: float) -> None:
    # Functions reachability
    sentence = f"""Fuzzers reach { "%.5s%%"%(str(reached_percentage)) } of all functions. """
    conclusions.append(
        html_helpers.HTMLConclusion(severity=int(reached_percentage * 0.1),
                                    title=sentence,
                                    description=""))

    # Complexity reachability
    percentage_str = "%.5s%%" % str(reached_complexity_percentage)
    sentence = f"Fuzzers reach { percentage_str } of cyclomatic complexity. "
    conclusions.append(
        html_helpers.HTMLConclusion(severity=int(reached_percentage * 0.1),
                                    title=sentence,
                                    description=""))


def create_fuzzer_detailed_section(
        proj_profile: project_profile.MergedProjectProfile,
        profile: fuzzer_profile.FuzzerProfile,
        table_of_contents: html_helpers.HtmlTableOfContents, tables: List[str],
        curr_tt_profile: int, conclusions: List[html_helpers.HTMLConclusion],
        extract_conclusion: bool, fuzzer_table_data: Dict[str, Any],
        dump_files: bool) -> str:
    html_string = ""
    html_string += html_helpers.html_add_header_with_link(
        f"Fuzzer: {profile.identifier}", html_helpers.HTML_HEADING.H2,
        table_of_contents)

    # Calltree fixed-width image
    html_string += html_helpers.html_add_header_with_link(
        "Call tree",
        html_helpers.HTML_HEADING.H3,
        table_of_contents,
        link=f"call_tree_{curr_tt_profile}")

    from fuzz_introspector.analyses import calltree_analysis as cta
    calltree_analysis = cta.FuzzCalltreeAnalysis()
    calltree_analysis.dump_files = dump_files
    calltree_file_name = calltree_analysis.create_calltree(profile)

    html_string += "<p class='no-top-margin'>"
    html_string += html_constants.INFO_CALLTREE_DESCRIPTION
    html_string += html_constants.INFO_CALLTREE_LINK_BUTTON.format(
        calltree_file_name)

    html_string += ("<p class='no-top-margin'>"
                    "Call tree overview bitmap:"
                    "</p>")

    colormap_file_prefix = profile.identifier
    if "/" in colormap_file_prefix:
        colormap_file_prefix = colormap_file_prefix.replace("/", "_")
    image_name = f"{colormap_file_prefix}_colormap.png"

    color_list = create_horisontal_calltree_image(image_name, profile,
                                                  dump_files)
    html_string += f"<img class=\"colormap\" src=\"{image_name}\">"

    # At this point we want to ensure there is coverage in order to proceed.
    # If there is no code coverage then the remaining will be quite bloat
    # in that it's all dependent on code coverage. As such we exit early
    # if there is none.
    if not proj_profile.has_coverage_data():
        html_string += (
            "<p>The project has no code coverage. Will not display blockers "
            "as blockers depend on code coverage.</p>")
        return html_string

    color_dictionary = {
        "red": 0,
        "gold": 0,
        "yellow": 0,
        "greenyellow": 0,
        "lawngreen": 0
    }
    for color in color_list:
        color_dictionary[color] = color_dictionary[color] + 1
    html_string += ("<p>The distribution of callsites in terms of coloring is")

    html_string += ("<table><tr>"
                    "<th style=\"text-align: left;\">Color</th>"
                    "<th style=\"text-align: left;\">Runtime hitcount</th>"
                    "<th style=\"text-align: left;\">Callsite count</th>"
                    "<th style=\"text-align: left;\">Percentage</th>"
                    "</tr>")
    for _min, _max, color, rgb_code in constants.COLOR_CONSTANTS:
        html_string += (f"<tr><td style=\"color:{color}; "
                        f"text-shadow: -1px 0 black, 0 1px black, "
                        f"1px 0 black, 0 -1px black;\"><b>{color}</b></td>")
        if _max == 1:
            interval = "0"
        elif _max > 1000:
            interval = f"{_min}+"
        else:
            interval = f"[{_min}:{_max-1}]"
        html_string += f"<td>{interval}</td>"
        html_string += f"<td>{color_dictionary[color]}</td>"
        if len(color_list) > 0:
            f1 = float(color_dictionary[color])
            f2 = float(len(color_list))
            percentage_c = (f1 / f2) * 100.0
        else:
            percentage_c = 0.0
        percentage_s = str(percentage_c)[0:4]
        html_string += f"<td>{percentage_s}%</td>"
        html_string += "</tr>"

    # Add a row with total amount of callsites
    html_string += f"<tr><td>All colors</td><td>{len(color_list)}</td><td>100</td></tr>"
    html_string += "</table>"
    html_string += "</p>"

    # Decide what kind of blockers to report: if branch blockers are not present,
    # fall back to calltree-based blockers.
    if profile.branch_blockers:
        # Populate branch blocker table
        html_fuzz_blocker_table = calltree_analysis.create_branch_blocker_table(
            profile, tables, calltree_file_name, 12)
    else:
        # Fuzz blocker table based on calltree
        html_fuzz_blocker_table = calltree_analysis.create_fuzz_blocker_table(
            profile, tables, calltree_file_name, file_link=calltree_file_name)
    if html_fuzz_blocker_table is not None:
        html_string += html_helpers.html_add_header_with_link(
            "Fuzz blockers",
            html_helpers.HTML_HEADING.H3,
            table_of_contents,
            link=f"fuzz_blocker{curr_tt_profile}")
        html_string += html_fuzz_blocker_table

    profile.write_stats_to_summary_file()
    # Table with all functions hit by this fuzzer
    html_string += html_helpers.html_add_header_with_link(
        "Runtime coverage analysis",
        html_helpers.HTML_HEADING.H3,
        table_of_contents,
        link=f"functions_cov_hit_{curr_tt_profile}")
    table_name = f"myTable{len(tables)}"

    # Add this table name to fuzzer_table_data
    fuzzer_table_data[table_name] = []

    tables.append(table_name)
    func_hit_table_string = ""
    func_hit_table_string += html_helpers.html_create_table_head(
        tables[-1], [("Function name", ""), ("source code lines", ""),
                     ("source lines hit", ""), ("percentage hit", "")], 1,
        "desc")

    total_hit_functions = 0
    if profile.coverage is not None:
        for funcname in profile.coverage.covmap:
            (total_func_lines, hit_lines,
             hit_percentage) = profile.get_cov_metrics(funcname)

            if hit_percentage is not None:
                if (hit_lines and hit_lines > 0):
                    total_hit_functions += 1
                fuzzer_table_data[table_name].append({
                    "Function name":
                    funcname,
                    "source code lines":
                    total_func_lines,
                    "source lines hit":
                    hit_lines,
                    "percentage hit":
                    "%.5s" % (str(hit_percentage)) + "%"
                })
            else:
                logger.error("Could not write coverage line for function %s" %
                             funcname)
    func_hit_table_string += "</table>"

    # Get how many functions are covered relative to reachability
    uncovered_reachable_funcs = len(
        profile.get_cov_uncovered_reachable_funcs())
    reachable_funcs = len(profile.functions_reached_by_fuzzer)
    reached_funcs = reachable_funcs - uncovered_reachable_funcs
    try:
        cov_reach_proportion = (float(reached_funcs) /
                                float(reachable_funcs)) * 100.0
    except Exception:
        logger.info("reachable funcs is 0")
        cov_reach_proportion = 0.0
    str_percentage = "%.5s%%" % str(cov_reach_proportion)
    json_report.add_fuzzer_key_value_to_report(
        profile.identifier, "coverage-blocker-stats", {
            "reachable-funcs": reachable_funcs,
            "reached-funcs": reached_funcs,
            "cov-reach-proportion": cov_reach_proportion,
        })
    if extract_conclusion:
        if cov_reach_proportion < 30.0:
            conclusions.append(
                html_helpers.HTMLConclusion(
                    2, f"Fuzzer { profile.identifier } is blocked:",
                    (f"The runtime code coverage of { profile.identifier } "
                     f"covers { str_percentage } of its statically reachable code. "
                     f"This means there is some place that blocks the fuzzer "
                     f"to continue exploring more code at run time. ")))

    html_string += "<div style=\"display: flex; margin-bottom: 10px;\">"
    html_string += html_helpers.get_simple_box("Covered functions",
                                               str(total_hit_functions))
    html_string += html_helpers.get_simple_box(
        "Functions that are reachable but not covered",
        str(uncovered_reachable_funcs))

    html_string += html_helpers.get_simple_box("Reachable functions",
                                               str(reachable_funcs))
    html_string += html_helpers.get_simple_box(
        "Percentage of reachable functions covered",
        "%s%%" % str(round(cov_reach_proportion, 2)))
    html_string += "</div>"
    html_string += html_constants.INFO_SUM_OF_COVERED_FUNCS_EQ_REACHABLE_FUNCS

    if total_hit_functions > reachable_funcs:
        html_string += html_constants.WARNING_TOTAL_FUNC_OVER_REACHABLE_FUNC

    html_string += func_hit_table_string

    # Table showing which files this fuzzer hits.
    html_string += html_helpers.html_add_header_with_link(
        "Files reached",
        html_helpers.HTML_HEADING.H3,
        table_of_contents,
        link=f"files_hit_{curr_tt_profile}")
    tables.append(f"myTable{len(tables)}")
    html_string += html_helpers.html_create_table_head(tables[-1],
                                                       [("filename", ""),
                                                        ("functions hit", "")])
    for k in profile.file_targets:
        html_string += html_helpers.html_table_add_row(
            [k, len(profile.file_targets[k])])
    html_string += "</table>\n"
    return html_string


def create_html_footer(tables):
    """Create an array of table ids wrapped in a <script> tag, and close
    <body> and <html> tags.
    """
    html_footer = "<script>\n"

    # Create array of all table ids
    html_footer += "var tableIds = ["
    counter = 0
    for tablename in tables:
        html_footer += f"'{tablename}'"
        if counter != len(tables) - 1:
            html_footer += ", "
        else:
            html_footer += "];\n"
        counter += 1

    # Closing tags
    html_footer += ("</script>\n")
    html_footer += ("</body>\n")
    html_footer += ("</html>\n")
    return html_footer


def write_content_to_html_files(html_full_doc, all_functions_json_html,
                                fuzzer_table_data):
    """Writes the content of the HTML static website to the relevant files.

    :param html_full_doc: content of the main fuzz_report.html file

    :param all_functions_json_html: dictionary in json format for all functions
      in the all functions table. These will be written ot a javascript file
      that is then loaded dynamically in the browser to reduce overhead of
      loading it all by way of hte .html file.

    :param fuzzer_table_data: data for tables for each fuzzer, in the detailed
      fuzzer section. To be written in a javascript file that is loaded
      dynamically.
    """
    # Dump the HTML report.
    with open(constants.HTML_REPORT, 'w') as report_file:
        report_file.write(html_helpers.prettify_html(html_full_doc))

    # Dump function data to the relevant javascript file.
    with open(constants.ALL_FUNCTION_JS, 'w') as all_function_file:
        all_function_file.write("var all_functions_table_data = ")
        all_function_file.write(json.dumps(all_functions_json_html))

    # Dump table data to relevant javascript file.
    with open(constants.FUZZER_TABLE_JS, 'w') as js_file_fd:
        js_file_fd.write("var fuzzer_table_data = ")
        js_file_fd.write(json.dumps(fuzzer_table_data))

    # Copy all of the styling into the directory.
    styling.copy_style_files(os.getcwd())


def create_html_report(profiles: List[fuzzer_profile.FuzzerProfile],
                       proj_profile: project_profile.MergedProjectProfile,
                       analyses_to_run: List[str], output_json: List[str],
                       coverage_url: str, basefolder: str, report_name: str,
                       dump_files: bool) -> None:
    """
    Logs a complete report. This is the current main place for looking at
    data produced by fuzz introspector.
    This method will return a dict contains analyser name to instance
    mapping that requires separate json report generation to avoid
    reruning those analysing process.
    """
    tables: List[str] = list()
    table_of_contents: html_helpers.HtmlTableOfContents = html_helpers.HtmlTableOfContents(
    )
    conclusions: List[html_helpers.HTMLConclusion] = []

    logger.info(" - Creating HTML report")

    if not proj_profile.has_coverage_data():
        conclusions.append(
            html_helpers.HTMLConclusion(
                severity=0,
                title="No coverage data was found",
                description=html_constants.WARNING_NO_COVERAGE))

    # Create html header, which will be used to assemble the doc at the
    # end of this function.
    html_header = html_helpers.html_get_header()

    # Start creation of core html
    html_body_start = '<div class="content-section">'
    html_overview = "<div class=\"report-box\">"
    html_overview += "<b>Report generation date:</b>"
    html_overview += datetime.today().strftime('%Y-%m-%d')
    html_overview += "<br>"

    html_overview += html_helpers.html_add_header_with_link(
        f"Project overview: {report_name}",
        html_helpers.HTML_HEADING.H1,
        table_of_contents,
        link="Project-overview")
    proj_profile.write_stats_to_summary_file()
    html_overview += "<div class=\"collapsible\">"

    # Project overview
    # html_overview += html_helpers.html_add_header_with_link(
    #   "Project information", 2, table_of_contents)

    #############################################
    # Section with high level suggestions
    #############################################
    html_report_top = html_helpers.html_add_header_with_link(
        "High level conclusions", html_helpers.HTML_HEADING.H2,
        table_of_contents)

    #############################################
    # Reachability overview
    #############################################
    logger.info(" - Creating reachability overview table")
    html_report_core = html_helpers.html_add_header_with_link(
        "Reachability and coverage overview", html_helpers.HTML_HEADING.H2,
        table_of_contents)
    tables.append(f"myTable{len(tables)}")
    html_report_core += "<div style=\"display: flex; max-width: 800px\">"
    html_report_core += create_boxed_top_summary_info(tables,
                                                      proj_profile,
                                                      conclusions,
                                                      True,
                                                      display_coverage=True)
    # Boxed summary
    html_report_core += "</div>"

    # .collapsible
    html_report_core += "</div>"

    # report-box
    html_report_core += "</div>"

    #############################################
    # Table with overview of all fuzzers.
    #############################################
    logger.info(" - Creating table with overview of all fuzzers")
    html_report_core += "<div class=\"report-box\">"
    html_report_core += html_helpers.html_add_header_with_link(
        "Fuzzers overview", html_helpers.HTML_HEADING.H1, table_of_contents)
    html_report_core += "<div class=\"collapsible\">"
    tables.append(f"myTable{len(tables)}")
    html_report_core += create_overview_table(tables, profiles)

    # report-box
    html_report_core += "</div>"  # .collapsible
    html_report_core += "</div>"

    #############################################
    # Table with details about all functions in the target project.
    #############################################
    logger.info(
        " - Creating table with information about all functions in target")
    html_report_core += "<div class=\"report-box\">"
    html_report_core += html_helpers.html_add_header_with_link(
        "Project functions overview", html_helpers.HTML_HEADING.H1,
        table_of_contents)
    html_report_core += "<div class=\"collapsible\">"
    html_report_core += html_constants.INFO_ALL_FUNCTION_OVERVIEW_TEXT

    table_id = "fuzzers_overview_table"
    tables.append(table_id)
    (all_function_table, all_functions_json_html,
     all_functions_json_report) = create_all_function_table(
         tables, proj_profile, coverage_url, basefolder, table_id)
    html_report_core += all_function_table
    html_report_core += "</div>"  # .collapsible
    html_report_core += "</div>"  # report box

    # Dump all functions in json report
    json_report.add_project_key_value_to_report("all-functions",
                                                all_functions_json_report)

    #############################################
    # Section with details about each fuzzer, including calltree.
    #############################################
    logger.info(" - Creating section with details about each fuzzer")
    fuzzer_table_data: Dict[str, Any] = dict()
    html_report_core += "<div class=\"report-box\">"
    html_report_core += html_helpers.html_add_header_with_link(
        "Fuzzer details", html_helpers.HTML_HEADING.H1, table_of_contents)
    html_report_core += "<div class=\"collapsible\">"
    for profile_idx in range(len(profiles)):
        html_report_core += create_fuzzer_detailed_section(
            proj_profile, profiles[profile_idx], table_of_contents, tables,
            profile_idx, conclusions, True, fuzzer_table_data, dump_files)
    html_report_core += "</div>"  # .collapsible
    html_report_core += "</div>"  # report box

    #############################################
    # Handle optional analyses
    #############################################
    logger.info(" - Handling optional analyses")
    html_report_core += "<div class=\"report-box\">"
    html_report_core += html_helpers.html_add_header_with_link(
        "Analyses and suggestions", html_helpers.HTML_HEADING.H1,
        table_of_contents)
    html_report_core += "<div class=\"collapsible\">"

    # Combine and distinguish analyser requires output in html or both (html and json)
    combined_analyses = analyses_to_run
    for analyses in output_json:
        if analyses not in analyses_to_run:
            combined_analyses.append(analyses)
    analysis_array = analysis.get_all_analyses()
    for analysis_interface in analysis_array:
        analysis_name = analysis_interface.get_name()
        if analysis_name in combined_analyses:
            analysis_instance = analysis.instantiate_analysis_interface(
                analysis_interface)
            analysis_instance.dump_files = dump_files

            html_string = analysis_instance.analysis_func(
                table_of_contents, tables, proj_profile, profiles, basefolder,
                coverage_url, conclusions)
            if analysis_name in analyses_to_run:
                html_report_core += html_string
    html_report_core += "</div>"  # .collapsible
    html_report_core += "</div>"  # report box

    #############################################
    # End of optional analyses
    #############################################

    #############################################
    # Create top level conclusions
    #############################################
    html_report_top += html_helpers.create_conclusions_box(conclusions)

    # Wrap up the HTML generation
    # Close the content div and content_wrapper
    html_body_end = "</div>\n</div>\n"

    # Javascript files/references to add to report.
    js_files = styling.MAIN_JS_FILES
    js_files.append(constants.ALL_FUNCTION_JS)
    js_files.append(constants.OPTIMAL_TARGETS_ALL_FUNCTIONS)
    js_files.append(constants.FUZZER_TABLE_JS)
    js_files.extend(styling.JAVASCRIPT_REMOTE_SCRIPTS)
    for js_file in js_files:
        html_body_end += f"<script src=\"{js_file}\"></script>"

    ###########################
    # Footer
    ###########################
    html_footer = create_html_footer(tables)

    ###########################
    # Fix up table of contents.
    ###########################
    html_toc_string = html_helpers.html_get_table_of_contents(
        table_of_contents, coverage_url, profiles, proj_profile)

    # Assemble the final HTML report and write it to a file.
    html_full_doc = (html_header + html_toc_string + html_body_start +
                     html_overview + html_report_top + html_report_core +
                     html_body_end + html_footer)

    if dump_files:
        write_content_to_html_files(html_full_doc, all_functions_json_html,
                                    fuzzer_table_data)
