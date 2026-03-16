def convert_to_html_list(issues_list):
    """
    Converts a list of dictionaries (with 'link' and 'title' keys) into
    an HTML unordered list (<ul>) with anchor tags (<a>).

    Args:
        issues_list (list): A list of dictionaries, where each dictionary
                            must contain 'link' and 'title' keys.

    Returns:
        str: A string containing the formatted HTML unordered list.
    """
    if not issues_list:
        return "<ul><li>No issues found.</li></ul>"

    html_output = "<ul>\n"
    for issue in issues_list:
        link = issue.get("link", "#")
        title = issue.get("title", "Untitled Issue")
        list_item = f'\t<li><a href="{link}" target="_blank">{title}</a></li>\n'
        html_output += list_item

    html_output += "</ul>"

    return html_output
