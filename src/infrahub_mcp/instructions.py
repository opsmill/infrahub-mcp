"""Server instructions: the guidance every MCP client can pass to the model.

Prompts are selected by the user and resources are attached by the host, so
neither reaches the model on its own. Server instructions do, in every client
that passes them on. The same text is included in the ``infrahub_agent``
prompt so the two cannot drift apart.

Content rules: ``specs/004-schema-discovery-guidance/contracts/server-instructions.md``.
"""

_OVERVIEW = """\
Infrahub stores infrastructure data as nodes of typed kinds (for example DcimDevice), on branches.

Schema first:
- If you do not know the exact kind name, call get_schema() to list the kinds.
- If you do not know a kind's attribute, relationship or filter names, call get_schema(kind="<Kind>").
- Never guess kind names, attribute names or filter keys.
- If that schema is already in this conversation, use it and do not fetch it again.

Choosing a tool:
- Nodes of one kind, including "how many": get_nodes. Its total_count gives the count without GraphQL; \
pass limit=1 when you only need the count.
- How two nodes are connected, or what a node affects: find_paths and find_reachable, not nested GraphQL.

Filter keys (for example role__value) are the ones get_schema(kind=...) lists under "filters". \
In get_nodes they go in the filters argument. In GraphQL (query_graphql) they go directly on the kind's query; \
there is no "filters" argument. Example:
  DcimDevice(role__value: "edge") { count edges { node { id name { value } } } }

Results that contain lists use TOON: a header names the fields once, then each indented row is one record."""

_RESOURCE_TOOLS = """\
Other data: read_resource(uri="infrahub://branches") lists the branches; \
read_resource(uri="infrahub://graphql-schema") returns the GraphQL schema of the default branch."""

_ACCESS_READ_WRITE = """\
Access: read and write. The first write creates a session branch; the default branch is never changed directly. \
Read tools use the default branch unless you pass branch; to read your own changes, pass the session branch \
that get_session_info returns. When the changes are ready, call propose_changes to open a proposed change \
for human review."""

_ACCESS_READ_ONLY = "Access: read-only. This server offers no tools that change data."


def build_instructions(*, read_only: bool, resources_as_tools: bool) -> str:
    """Return the server instructions for the given server settings.

    Args:
        read_only: When True, the text names no write tool and no session-branch workflow.
        resources_as_tools: When True, the text names the URIs ``read_resource`` can read.

    Returns:
        The instructions text, under 2,000 characters in every variant.
    """
    sections = [_OVERVIEW]
    if resources_as_tools:
        sections.append(_RESOURCE_TOOLS)
    sections.append(_ACCESS_READ_ONLY if read_only else _ACCESS_READ_WRITE)
    return "\n\n".join(sections)
