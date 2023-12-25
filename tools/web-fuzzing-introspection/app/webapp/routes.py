# Copyright 2023 Fuzz Introspector Authors
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

import random
import json

from flask import Blueprint, render_template, request, redirect

#from app.site import models
from . import models

# Use these during testing.
#from app.site import test_data
from . import data_storage

blueprint = Blueprint('site', __name__, template_folder='templates')

gtag = None


def get_coverage_report_url(project_name, datestr, language):
    if language == 'java' or language == 'python' or language == 'go':
        file_report = "index.html"
    else:
        file_report = "report.html"
    base_url = 'https://storage.googleapis.com/oss-fuzz-coverage/{0}/reports/{1}/linux/{2}'
    project_url = base_url.format(project_name, datestr.replace("-", ""),
                                  file_report)
    return project_url


def get_functions_of_interest(project_name):
    all_functions = data_storage.get_functions()
    project_functions = []
    for function in all_functions:
        if function.project == project_name:
            if function.runtime_code_coverage < 20.0:
                project_functions.append(function)

    # Filter based on accummulated cyclomatic complexity and low coverage
    sorted_functions_of_interest = sorted(
        project_functions,
        key=lambda x:
        (-x.accummulated_cyclomatic_complexity, -x.runtime_code_coverage))

    return sorted_functions_of_interest


def get_frontpage_summary_stats():
    # Get total number of projects
    all_projects = data_storage.get_projects()

    projects_to_use = []
    # Only include fuzz introspector projects
    #for project in all_projects:
    #    if project.introspector_data != None:
    #        projects_to_use.append(project)

    total_number_of_projects = len(all_projects)
    total_fuzzers = sum([project.fuzzer_count for project in all_projects])
    total_functions = len(data_storage.get_functions())
    language_count = {
        'c': 0,
        'python': 0,
        'c++': 0,
        'java': 0,
        'go': 0,
        'rust': 0,
        'swift': 0
    }
    for project in all_projects:
        try:
            language_count[project.language] += 1
        except KeyError:
            continue

    # wrap it in a DBSummary
    db_summary = models.DBSummary(all_projects, total_number_of_projects,
                                  total_fuzzers, total_functions,
                                  language_count)
    return db_summary


def get_project_with_name(project_name):
    all_projects = data_storage.get_projects()
    for project in all_projects:
        if project.name == project_name:
            return project

    # TODO: Handle the case where there is no such project.
    return None


def get_fuction_with_name(function_name, project_name):
    all_functions = data_storage.get_functions()
    for function in all_functions:
        if function.name == function_name and function.project == project_name:
            return function

    # TODO: Handle the case where there is no such function
    return all_functions[0]


def get_all_related_functions(primary_function):
    all_functions = data_storage.get_functions()
    related_functions = []
    for function in all_functions:
        if function.name == primary_function.name and function.project != primary_function.project:
            related_functions.append(function)
    return related_functions


@blueprint.route('/')
def index():
    db_summary = get_frontpage_summary_stats()
    db_timestamps = data_storage.DB_TIMESTAMPS
    print("Length of timestamps: %d" % (len(db_timestamps)))
    # Maximum projects
    max_proj = 0
    max_fuzzer_count = 0
    max_function_count = 0
    max_line_count = 0
    for db_timestamp in db_timestamps:
        max_proj = max(db_timestamp.project_count, max_proj)
        max_fuzzer_count = max(db_timestamp.fuzzer_count, max_fuzzer_count)
        max_function_count = max(db_timestamp.function_count,
                                 max_function_count)
        max_line_count = max(max_line_count,
                             db_timestamp.accummulated_lines_total)

    max_proj = int(max_proj * 1.2)
    max_fuzzer_count = int(max_fuzzer_count * 1.2)
    max_function_count = int(max_function_count * 1.2)
    max_line_count = int(max_line_count * 1.2)

    oss_fuzz_total_number = len(data_storage.get_build_status())
    return render_template('index.html',
                           gtag=gtag,
                           db_summary=db_summary,
                           db_timestamps=db_timestamps,
                           max_proj=max_proj,
                           max_fuzzer_count=max_fuzzer_count,
                           max_function_count=max_function_count,
                           oss_fuzz_total_number=oss_fuzz_total_number,
                           max_line_count=max_line_count)


@blueprint.route('/function-profile', methods=['GET'])
def function_profile():
    function_profile = get_fuction_with_name(
        request.args.get('function', 'none'),
        request.args.get('project', 'none'))

    related_functions = get_all_related_functions(function_profile)
    return render_template('function-profile.html',
                           gtag=gtag,
                           related_functions=related_functions,
                           function_profile=function_profile)


@blueprint.route('/project-profile', methods=['GET'])
def project_profile():
    #print(request.args.get('project', 'none'))

    target_project_name = request.args.get('project', 'none')

    project = get_project_with_name(target_project_name)

    if project != None:
        # Get the build status of the project
        all_build_status = data_storage.get_build_status()
        project_build_status = dict()
        for build_status in all_build_status:
            if build_status.project_name == project.name:
                project_build_status = build_status
                break

        # Get statistics of the project
        project_statistics = data_storage.PROJECT_TIMESTAMPS
        real_stats = []
        latest_statistics = None
        for ps in project_statistics:
            if ps.project_name == project.name:
                real_stats.append(ps)
                latest_statistics = ps

        # Get functions of interest for the project
        # Display a maximum of 10 functions of interest. Down the line, this
        # should be more carefully constructed, perhaps based on a variety of
        # heuristics.
        functions_of_interest = list()
        functions_of_interest_all = get_functions_of_interest(project.name)
        for i in range(min(10, len(functions_of_interest_all))):
            func_of_interest = functions_of_interest_all[i]
            functions_of_interest.append({
                'function_name':
                func_of_interest.name,
                'source_file':
                func_of_interest.function_filename,
                'complexity':
                func_of_interest.accummulated_cyclomatic_complexity,
                'code_coverage':
                func_of_interest.runtime_code_coverage,
                'code_coverage_url':
                func_of_interest.code_coverage_url,
            })

        return render_template('project-profile.html',
                               gtag=gtag,
                               project=project,
                               project_statistics=real_stats,
                               has_project_details=True,
                               has_project_stats=True,
                               project_build_status=project_build_status,
                               functions_of_interest=functions_of_interest,
                               latest_coverage_report=None,
                               latest_statistics=latest_statistics)

    # Either this is a wrong project or we only have a build status for it
    all_build_status = data_storage.get_build_status()
    for build_status in all_build_status:
        if build_status.project_name == target_project_name:
            project = models.Project(
                name=build_status.project_name,
                language=build_status.language,
                date="",
                fuzzer_count=0,
                coverage_data=None,
                introspector_data=None,
            )

            # Get statistics of the project
            project_statistics = data_storage.PROJECT_TIMESTAMPS
            real_stats = []
            datestr = None
            latest_statistics = None
            for ps in project_statistics:
                if ps.project_name == project.name:
                    real_stats.append(ps)
                    datestr = ps.date
                    latest_statistics = ps

            if len(real_stats) > 0:
                latest_coverage_report = get_coverage_report_url(
                    build_status.project_name, datestr, build_status.language)
            else:
                latest_coverage_report = None
            return render_template(
                'project-profile.html',
                gtag=gtag,
                project=project,
                project_statistics=real_stats,
                has_project_details=False,
                has_project_stats=len(real_stats) > 0,
                project_build_status=build_status,
                functions_of_interest=[],
                latest_coverage_report=latest_coverage_report,
                coverage_date=datestr,
                latest_statistics=latest_statistics)
    print("Nothing to do. We shuold probably have a 404")
    return redirect("/")


@blueprint.route('/function-search')
def function_search():
    info_msg = None
    MAX_MATCHES_TO_DISPLAY = 900
    query = request.args.get('q', '')
    print("query: { %s }" % (query))
    print("Length of functions: %d" % (len(data_storage.get_functions())))
    if query == '':
        # Pick a random interesting query
        # Some queries involving fuzzing-interesting targets.
        interesting_query_roulette = [
            'deserialize', 'parse', 'parse_xml', 'read_file', 'read_json',
            'read_xml', 'message', 'request', 'parse_header', 'parse_request',
            'header', 'decompress', 'file_read'
        ]
        interesting_query = random.choice(interesting_query_roulette)
        tmp_list = []
        for function in data_storage.get_functions():
            if interesting_query in function.name:
                tmp_list.append(function)
        functions_to_display = tmp_list

        # Shuffle to give varying results each time
        random.shuffle(functions_to_display)

        total_matches = len(functions_to_display)
        if total_matches >= 100:
            functions_to_display = functions_to_display[:100]
        info_msg = f"No query was given, picked the query \"{interesting_query}\" for this"
    else:
        tmp_list = []
        for function in data_storage.get_functions():
            if query in function.name:
                tmp_list.append(function)
        functions_to_display = tmp_list

        total_matches = len(functions_to_display)
        if total_matches >= MAX_MATCHES_TO_DISPLAY:
            functions_to_display = functions_to_display[
                0:MAX_MATCHES_TO_DISPLAY]
            info_msg = f"Found {total_matches} matches. Only showing the first {MAX_MATCHES_TO_DISPLAY}."

    return render_template('function-search.html',
                           gtag=gtag,
                           all_functions=functions_to_display,
                           info_msg=info_msg)


@blueprint.route('/projects-overview')
def projects_overview():
    # Get statistics of the project
    project_statistics = data_storage.PROJECT_TIMESTAMPS
    latest_coverage_profiles = dict()
    real_stats = []
    latest_statistics = None
    for ps in project_statistics:
        latest_coverage_profiles[ps.project_name] = ps

    return render_template('projects-overview.html',
                           gtag=gtag,
                           all_projects=latest_coverage_profiles.values())


def oracle_1(all_functions, all_projects):
    tmp_list = []
    project_count = dict()
    for function in all_functions:
        if "parse" not in function.name:
            continue

        if (function.runtime_code_coverage == 0.0
                and project_count.get(function.project, 0) < 5
                and function.accummulated_cyclomatic_complexity > 200):

            to_continue = False
            for proj in all_projects:
                if proj.name == function.project and proj.language in {
                        'c', 'c++'
                }:
                    to_continue = True
            if not to_continue:
                continue
            tmp_list.append(function)
            current_count = project_count.get(function.project, 0)
            current_count += 1
            project_count[function.project] = current_count

    functions_to_display = tmp_list
    funcs_max_to_display = 4000
    total_matches = len(functions_to_display)
    if total_matches >= funcs_max_to_display:
        functions_to_display = functions_to_display[:funcs_max_to_display]

    return functions_to_display


def oracle_2(all_functions, all_projects):
    tmp_list = []
    project_count = dict()
    for function in all_functions:
        if len(function.function_arguments) != 2:
            continue

        if (function.function_arguments[0] != 'char *'
                or function.function_arguments[1] != "int"):
            continue

        if function.accummulated_cyclomatic_complexity < 150:
            continue

        tmp_list.append(function)
        current_count = project_count.get(function.project, 0)
        current_count += 1
        project_count[function.project] = current_count

    functions_to_display = tmp_list
    funcs_max_to_display = 4000
    total_matches = len(functions_to_display)
    if total_matches >= funcs_max_to_display:
        functions_to_display = functions_to_display[:funcs_max_to_display]

    return functions_to_display


@blueprint.route('/target_oracle')
def target_oracle():
    all_projects = data_storage.get_projects()
    all_functions = data_storage.get_functions()

    functions_to_display = []

    total_funcs = set()
    oracle_pairs = [(oracle_1, "heuristic 1"), (oracle_2, "heuristic 2")]
    for oracle, heuristic_name in oracle_pairs:
        func_targets = oracle(all_functions, all_projects)
        for func in func_targets:
            if func in total_funcs:
                continue
            total_funcs.add(func)
            functions_to_display.append((func, heuristic_name))

    func_to_lang = dict()
    for func, heuristic in functions_to_display:
        language = 'c'
        for proj in all_projects:
            if proj.name == func.project:
                language = proj.language
                break
        # We may overwrite here, and in that case we just use the new
        # heuristic for labeling.
        func_to_lang[func.name] = language

    return render_template('target-oracle.html',
                           gtag=gtag,
                           functions_to_display=functions_to_display,
                           func_to_lang=func_to_lang)


@blueprint.route('/indexing-overview')
def indexing_overview():
    build_status = data_storage.get_build_status()

    languages_summarised = dict()
    for bs in build_status:
        if bs.language not in languages_summarised:
            languages_summarised[bs.language] = {
                'all': 0,
                'fuzz_build': 0,
                'cov_build': 0,
                'introspector_build': 0
            }
        languages_summarised[bs.language]['all'] += 1
        languages_summarised[bs.language][
            'fuzz_build'] += 1 if bs.fuzz_build_status == True else 0
        languages_summarised[bs.language][
            'cov_build'] += 1 if bs.coverage_build_status == True else 0
        languages_summarised[bs.language][
            'introspector_build'] += 1 if bs.introspector_build_status == True else 0

    print(json.dumps(languages_summarised))

    return render_template('indexing-overview.html',
                           gtag=gtag,
                           all_build_status=build_status,
                           languages_summarised=languages_summarised)


@blueprint.route('/about')
def about():
    return render_template('about.html', gtag=gtag)


@blueprint.route('/api')
def api():
    return render_template('api.html', gtag=gtag)


@blueprint.route('/api/annotated-cfg')
def api_annotated_cfg():
    project_name = request.args.get('project', None)
    if project_name == None:
        return {'result': 'error', 'msg': 'Please provide project name'}

    target_project = None
    all_projects = data_storage.get_projects()
    for project in all_projects:
        if project.name == project_name:
            target_project = project
            break
    if target_project is None:
        return {'result': 'error', 'msg': 'Project not in the database'}

    try:
        return {
            'result': 'success',
            'project': {
                'name': project_name,
                'annotated_cfg': project.introspector_data['annotated_cfg'],
            }
        }
    except KeyError:
        return {'result': 'error', 'msg': 'Found no annotated CFG data.'}
    except TypeError:
        return {'result': 'error', 'msg': 'Found no introspector data.'}


@blueprint.route('/api/project-summary')
def api_project_summary():
    project_name = request.args.get('project', None)
    if project_name == None:
        return {'result': 'error', 'msg': 'Please provide project name'}
    target_project = None
    all_projects = data_storage.get_projects()
    for project in all_projects:
        if project.name == project_name:
            target_project = project
            break
    if target_project is None:
        return {'result': 'error', 'msg': 'Project not in the database'}

    return {
        'result': 'success',
        'project': {
            'name': project_name,
            'runtime_coverage_data': project.coverage_data,
            'introspector_data': project.introspector_data
        }
    }


@blueprint.route('/api/branch-blockers')
def branch_blockers():
    project_name = request.args.get('project', None)
    if project_name == None:
        return {'result': 'error', 'msg': 'Please provide project name'}

    target_project = None
    all_projects = data_storage.get_projects()
    for project in all_projects:
        if project.name == project_name:
            target_project = project
            break
    if target_project is None:
        return {'result': 'error', 'msg': 'Project not in the database'}

    all_branch_blockers = data_storage.get_blockers()

    project_blockers = []
    for blocker in all_branch_blockers:
        if blocker.project_name == project_name:
            project_blockers.append({
                'project_name':
                blocker.project_name,
                'function_name':
                blocker.function_name,
                'source_file':
                blocker.source_file,
                'src_linenumber':
                blocker.src_linenumber,
                'unique_blocked_coverage':
                blocker.unique_blocked_coverage,
                'blocked_unique_functions':
                blocker.blocked_unique_functions
            })
    return {'result': 'success', 'project_blockers': project_blockers}


@blueprint.route('/api/all-functions')
def api_project_all_functions():
    """Returns a json representation of all the functions in a given project"""
    project_name = request.args.get('project', None)
    if project_name == None:
        return {'result': 'error', 'msg': 'Please provide a project name'}

    # Get all of the functions
    all_functions = data_storage.get_functions()
    project_functions = []
    for function in all_functions:
        if function.project == project_name:
            project_functions.append(function)

    # Convert it to something we can return
    functions_to_return = list()
    for function in project_functions:
        functions_to_return.append({
            'function_name':
            function.name,
            'function_filename':
            function.function_filename,
            'raw_function_name':
            function.raw_function_name,
            'is_reached':
            function.is_reached,
            'accummulated_complexity':
            function.accummulated_cyclomatic_complexity,
            'function_argument_names':
            function.function_argument_names,
            'function_arguments':
            function.function_arguments,
            'reached_by_fuzzers':
            function.reached_by_fuzzers,
            'return_type':
            function.return_type,
            'runtime_coverage_percent':
            function.runtime_code_coverage,
        })
    return {'result': 'success', 'functions': functions_to_return}


@blueprint.route('/api/far-reach-but-low-coverage')
def far_reach_but_low_coverage():
    project_name = request.args.get('project', None)
    if project_name == None:
        return {'result': 'error', 'msg': 'Please provide project name'}  ##

    target_project = None
    all_projects = data_storage.get_projects()
    for project in all_projects:
        if project.name == project_name:
            target_project = project
            break
    if target_project is None:
        return {'result': 'error', 'msg': 'Project not in the database'}

    # Get functions of interest
    sorted_functions_of_interest = get_functions_of_interest(project_name)

    max_functions_to_show = 1000
    functions_to_return = list()
    idx = 0
    for function in sorted_functions_of_interest:
        if idx >= max_functions_to_show:
            break
        idx += 1
        functions_to_return.append({
            'function_name':
            function.name,
            'function_filename':
            function.function_filename,
            'runtime_coverage_percent':
            function.runtime_code_coverage,
            'accummulated_complexity':
            function.accummulated_cyclomatic_complexity,
            'function_arguments':
            function.function_arguments,
            'function_argument_names':
            function.function_argument_names,
            'return_type':
            function.return_type,
            'is_reached':
            function.is_reached,
            'reached_by_fuzzers':
            function.reached_by_fuzzers,
            'raw_function_name':
            function.raw_function_name,
        })

    return {'result': 'success', 'functions': functions_to_return}
