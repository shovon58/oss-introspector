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
"""Module for creating HTML reports"""

from typing import (
    Any,
    List,
    Optional,
    Tuple,
)

import os
import bs4
from enum import Enum

from fuzz_introspector import utils
from fuzz_introspector.datatypes import fuzzer_profile, project_profile


class HTML_HEADING(Enum):
    H1 = 1
    H2 = 2
    H3 = 3
    H4 = 4
    H5 = 5
    H6 = 6


class HTML_TOC_ENTRY:
    """Entry in the table of contents"""

    def __init__(self, entry_title: str, href_link: str,
                 heading_type: HTML_HEADING):
        self.entry_title = entry_title
        self.href_link = href_link
        self.heading_type = heading_type


class HtmlTableOfContents:
    """Helper class for representing a table of content"""

    def __init__(self):
        self.entries: List[HTML_TOC_ENTRY] = []

    def add_entry(self, entry_title, href_link, heading_type):
        toc_entry = HTML_TOC_ENTRY(entry_title, href_link, heading_type)
        self.entries.append(toc_entry)


class HTMLConclusion:
    """Represents high-level conclusions in HTML report

    :ivar int severity: Importance of conclusion. 100 max, 0 lowest.
    :ivar str title: One line description of conclusion.
    :ivar str description: Extended description.
    """

    def __init__(self, severity, title, description):
        self.title = title
        self.severity = severity
        self.description = description

    def __lt__(self, other):
        """Implemented for sorting list of conclusions"""
        return self.severity < other.severity


def html_table_add_row(elems: List[Any]) -> str:
    html_str = "<tr>\n"
    for elem in elems:
        html_str += f"<td>{elem}</td>\n"
    html_str += "</tr>\n"
    return html_str


def html_get_header(calltree: bool = False,
                    title: str = "Fuzz introspector") -> str:
    gtag_tracking = ""
    try:
        gtag = os.environ['G_ANALYTICS_TAG']
        gtag_tracking += f"""<!-- Google tag (gtag.js) -->
                <script async src="https://www.googletagmanager.com/gtag/js?id={gtag}"></script>
                <script>
                  window.dataLayer = window.dataLayer || [];
                  function gtag(){{dataLayer.push(arguments);}}
                  gtag('js', new Date());

                  gtag('config', '{gtag}');
                </script>\n"""
    except KeyError:
        gtag_tracking = ""

    header = f"""<html>
    <head>
        {gtag_tracking}
        <link
            rel='stylesheet'
            href='prism.css'>
        <link
            rel="stylesheet"
            href="https://unpkg.com/dracula-prism/dist/css/dracula-prism.css">
    </head>
        <body>
            <script
                src="https://code.jquery.com/jquery-3.6.0.min.js"
                integrity="sha256-/xUj+3OJU5yExlq6GSYGSHk7tPXikynS7ogEvDej/m4="
                crossorigin="anonymous">
            </script>
            <script
                src='https://cdn.datatables.net/1.10.25/js/jquery.dataTables.min.js'>
            </script>
            <link
                rel='stylesheet'
                href='https://cdn.datatables.net/1.10.25/css/jquery.dataTables.min.css'>
            <link
                rel='stylesheet'
                href='styles.css'>
            <link
                rel='stylesheet'
                href='https://cdn.datatables.net/buttons/2.2.2/css/buttons.dataTables.min.css'>"""
    # Add navbar to header
    header = header + html_get_navbar(title)
    if calltree:
        header = header + "<div class='content-wrapper calltree-page'>"
    else:
        header = header + "<div class='content-wrapper report-page'>"
    return header


def html_get_navbar(title: str) -> str:
    navbar = f"""
    <div class="top-navbar">
        <div class="top-navbar-title-wrapper">
            <div class="top-navbar-title" style="margin-bottom: 10px; font-size:25px">
                { title }
            </div>
            <div style="margin:0; font-size: 10px">
              For issues and ideas:
              <a href="https://github.com/ossf/fuzz-introspector/issues"
                 style="color:#FFFFFF;">
                https://github.com/ossf/fuzz-introspector/issues
              </a>
            </div>
        </div>
    </div>"""
    return navbar


def create_pfc_button(profiles: List[fuzzer_profile.FuzzerProfile],
                      coverage_url: str) -> str:
    html_string = ""
    html_string += """
                    <div class="yellow-button-wrapper"
                        style="position: relative; margin: 5px 0 30px 0">
                        <div class="yellow-button"
                        onclick="displayCollapseByName()" id="per-fuzzer-coverage-button">
                            Per-fuzzer coverage
                        </div>
                    <div class="per-fuzzer-coverage-dropdown" id="per-fuzzer-coverage-dropdown">"""
    for profile in profiles:
        target_name = profile.identifier
        target_coverage_url = utils.get_target_coverage_url(
            coverage_url, target_name, profile.target_lang)
        # get_target_coverage_url gives base folder. We must specify
        # HTML file for it to work on gcloud as there is no automatic
        # redirection.
        if profile.target_lang == "c-cpp":
            target_coverage_url += "/report.html"
        elif profile.target_lang == "python":
            target_coverage_url += "/index.html"
        elif profile.target_lang == "jvm":
            target_coverage_url += "/index.html"

        html_string += f"""
            <a href="{target_coverage_url}">
                <div class="pfc-list-item">
                    {target_name}
                </div>
            </a>"""
    html_string += "</div></div>"
    return html_string


def html_get_table_of_contents(
        table_of_contents: HtmlTableOfContents, coverage_url: str,
        profiles: List[fuzzer_profile.FuzzerProfile],
        proj_profile: project_profile.MergedProjectProfile) -> str:
    per_fuzzer_coverage_button = create_pfc_button(profiles, coverage_url)

    if proj_profile.target_lang == "c-cpp":
        cov_index = "report.html"
    elif proj_profile.target_lang == "python":
        cov_index = "index.html"
    elif proj_profile.target_lang == "jvm":
        cov_index = "index.html"

    html_toc_string = ""
    html_toc_string += f"""<div class="left-sidebar">\
                            <div class="left-sidebar-content-box"
                                style="display:flex;flex-direction:column;
                                 padding: 0 20px; margin-top: 30px">
                                <div class="yellow-button-wrapper"
                                    style="position: relative; margin: 30px 0 5px 0">
                                    <a href="{coverage_url}/{cov_index}">
                                        <div class="yellow-button">
                                            Project coverage
                                        </div>
                                    </a>
                                </div>
                        """
    if proj_profile.target_lang != "python":
        html_toc_string += f"{per_fuzzer_coverage_button}"

    html_toc_string += """</div>
                            <div class="left-sidebar-content-box">\
                                <h2 style="margin-top:0px">Table of contents</h2>"""

    for toc_entry in table_of_contents.entries:
        indentation = (toc_entry.heading_type.value - 1) * 16
        html_toc_string += "<div style='margin-left: %spx'>" % indentation
        html_toc_string += "    <a href=\"#%s\">%s</a>\n" % (
            toc_entry.href_link, toc_entry.entry_title)
        html_toc_string += "</div>\n"
    html_toc_string += '    </div>\
                        </div>'

    return html_toc_string


def html_add_header_with_link(header_title: str,
                              title_type: HTML_HEADING,
                              table_of_contents: HtmlTableOfContents,
                              link: Optional[str] = None,
                              experimental: Optional[bool] = False) -> str:
    if link is None:
        link = header_title.replace(" ", "-")

    if not experimental:
        table_of_contents.add_entry(header_title, link, title_type)

    html_attributes = ""
    if title_type == HTML_HEADING.H1 or experimental:
        html_attributes += " class=\"report-title\""

    html_string = f"<a id=\"{link}\">"
    html_string += (
        f"<h{title_type.value} {html_attributes}>{header_title}</h{title_type.value}>\n"
    )
    return html_string


def html_create_table_head(table_head: str,
                           items: List[Tuple[str, str]],
                           sort_by_column: int = 0,
                           sort_order: str = "asc") -> str:
    html_str = (
        f"<table id='{table_head}' class='cell-border compact stripe' "
        f"data-sort-by-column='{sort_by_column}' data-sort-order='{sort_order}'>"
    )
    html_str += "<thead><tr>\n"
    for column_title, column_description in items:
        if column_description == "":
            html_str += f"<th>{column_title}</th>\n"
        else:
            html_str += f"<th title='{column_description}'>{column_title}</th>\n"
    html_str += "</tr></thead><tbody>"
    return html_str


def get_simple_box(title: str, value: str) -> str:
    """Wraps a title and value in a simle HTML div box, where the box has some
    simple borders.
    """

    return f"""<div class="report-box"
                    style="flex: 1; display: flex; flex-direction: column;">
        <div style="font-size: 0.9rem;">
          {title}
        </div>
        <div style="font-size: 1.2rem; font-weight: 550;">
          {value}
        </div>
      </div>"""


def create_collapsible_element(non_collapsed: str, collapsed: str,
                               collapsible_id: str) -> str:
    """Creates a string followed by a <div> that is collapsible. We use this
    for displaying items in tables where the full substance of the item is
    too large to display by default for all items, but we still want the user
    to be able to see the full substance of the item on demand.
    """
    return f"""{ non_collapsed } : <div
    class='wrap-collabsible'>
        <input id='{collapsible_id}'
               class='toggle'
               type='checkbox'>
            <label for='{collapsible_id}'
                   class='lbl-toggle'>
                View List
            </label>
        <div class='collapsible-content'>
            <div class='content-inner'>
                <p>
                    {collapsed}
                </p>
            </div>
        </div>
    </div>"""


def create_percentage_graph(title: str, numerator: int,
                            denominator: int) -> str:
    """Creates a percentage tag within a <div> tag. This is used to show
    "how much X is of Y" for a {numerator, denominator} pair.
    """
    percentage = round(float(numerator) / float(denominator), 2) * 100.0
    subtitle = f"{numerator} / {denominator}"
    return f"""<div style="flex:1; margin-right: 20px"class="report-box mt-0">
            <div style="font-weight: 600; text-align: center;">
                {title}
            </div>
            <div class="flex-wrapper">
              <div class="single-chart">
                <svg viewBox="0 0 36 36" class="circular-chart green">
                  <path class="circle-bg"
                    d="M18 2.0845
                      a 15.9155 15.9155 0 0 1 0 31.831
                      a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                  <path class="circle"
                    stroke-dasharray="{percentage}, 100"
                    d="M18 2.0845
                      a 15.9155 15.9155 0 0 1 0 31.831
                      a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                  <text x="18" y="20.35" class="percentage">{str(percentage)[:4]}%</text>
                </svg>
              </div>
            </div>
            <div style="font-size: .9rem; color: #b5b5b5; text-align: center">
              {subtitle}
            </div>
        </div>"""


def prettify_html(html_doc: str) -> str:
    """Prettify a HTML document."""
    soup = bs4.BeautifulSoup(html_doc, "html.parser")
    try:
        pretty_html = soup.prettify()
    except RecursionError:
        pretty_html = html_doc
    return pretty_html
