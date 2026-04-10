## Infrahub MCP Server 1.0.1

| ✔ Tools (7) | ✔ Prompts (4) | ✔ Resources (3) | ✔ Logging | ~~<span style="opacity:0.6" class="error">✘ Completions</span>~~ | ~~<span style="opacity:0.6" class="error">✘ Tasks</span>~~ |
| --- | --- | --- | --- | --- | --- |

## 🛠️ Tools (7)

<table style="text-align: left;">
<thead>
    <tr>
        <th style="width: auto;"></th>
        <th style="width: auto;">Icon</th>
        <th style="width: auto;">Tool Name</th>
        <th style="width: auto;">Description</th>
        <th style="width: auto;">Inputs</th>
    </tr>
</thead>
<tbody style="vertical-align: top;">
        <tr>
            <td>1.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>get_nodes</b></code>
            </td>
            <td>Retrieve objects of a specific kind from Infrahub.<br/><br/>To discover available kinds, read the ``infrahub://schema`` resource.<br/>If your client does not support MCP resources, call the `<code>get_schema</code>` tool instead.<br/>To discover available filters for a kind, read ``infrahub://schema/{kind}``<br/>or call ``get_schema(kind='...')``.<br/><br/>Args:<br/>    kind: Kind of the objects to retrieve.<br/>    branch: Branch to query. Defaults to the default branch.<br/>    filters: Dictionary of filters to apply.<br/>    partial_match: Whether to use partial matching for string filters.<br/>    include_attributes: Return full attribute dicts instead of display labels only.<br/>    limit: Cap on results returned (default 50). Pass -1 for all.<br/><br/>Returns:<br/>    A list of display labels (default) or a TOON-encoded string of full attribute dicts.<br/><br/>Raises:<br/>    RuntimeError: Via `<code>_log_and_raise_error</code>` when the schema is not found or the query fails.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                    <li> <code>filters</code> : unknown<br /></li>
                    <li> <code>include_attributes</code> : boolean<br /></li>
                    <li> <code>kind</code> : string<br /></li>
                    <li> <code>limit</code> : integer<br /></li>
                    <li> <code>partial_match</code> : boolean<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>2.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>get_schema</b></code>
            </td>
            <td>Discover available schema kinds and their structure in Infrahub.<br/><br/>Call without arguments to list all available kinds.<br/>Call with a `<code>kind</code>` to see its attributes, relationships, and valid filter keys.<br/><br/>Prefer reading the ``infrahub://schema`` resource if your client supports<br/>MCP resources — this tool provides the same data for clients that don't.<br/><br/>Args:<br/>    kind: Optional kind to get detail for. Omit to list all kinds.<br/>    branch: Branch to query. Defaults to the default branch.<br/><br/>Returns:<br/>    JSON catalog (no kind) or TOON-encoded schema detail (with kind).</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                    <li> <code>kind</code> : string | null<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>3.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>node_delete</b></code>
            </td>
            <td>Delete a node in Infrahub on the active session branch.<br/><br/>The deletion is applied to the session branch only and is not visible on the<br/>default branch until a proposed change is merged.<br/>To discover available kinds, read the ``infrahub://schema`` resource.<br/>If your client does not support MCP resources, call the `<code>get_schema</code>`<br/>tool instead.<br/><br/>Parameters:<br/>    kind: Kind of the node.<br/>    id: UUID of the node to delete.<br/>    hfid: Human-friendly ID segments of the node to delete.<br/><br/>Returns:<br/>    Dict confirming deletion on success.</td>
            <td>
                <ul>
                    <li> <code>hfid</code> : string [ ] | null<br /></li>
                    <li> <code>id</code> : string | null<br /></li>
                    <li> <code>kind</code> : string<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>4.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>node_upsert</b></code>
            </td>
            <td>Create or update a node in Infrahub on the active session branch.<br/><br/>The session branch is auto-created on the first write of the session<br/>(``mcp/session-YYYYMMDD-<hex>``). Use `<code>propose_changes</code>` to open a<br/>review once your changes are ready.<br/>To discover available kinds and attributes, read the ``infrahub://schema``<br/>resource. If your client does not support MCP resources, call the<br/>`<code>get_schema</code>` tool instead.<br/><br/>- **Create**: omit both `<code>id</code>` and `<code>hfid</code>`.<br/>- **Update**: supply either `<code>id</code>` or `<code>hfid</code>` to identify the target node.<br/><br/>Only scalar attribute fields are accepted in `<code>data</code>`. To set relationship<br/>fields, use `<code>query_graphql</code>` with an appropriate GraphQL mutation.<br/><br/>Parameters:<br/>    kind: Node kind to create or update.<br/>    data: Flat attribute map ``{attribute_name: value}``.<br/>    id: UUID of the node to update (update mode).<br/>    hfid: Human-friendly ID segments of the node to update (update mode).<br/><br/>Returns:<br/>    Dict with node id, display_label, and branch on success.</td>
            <td>
                <ul>
                    <li> <code>data</code> : unknown<br /></li>
                    <li> <code>hfid</code> : string [ ] | null<br /></li>
                    <li> <code>id</code> : string | null<br /></li>
                    <li> <code>kind</code> : string<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>5.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>propose_changes</b></code>
            </td>
            <td>Open a proposed change (pull request) from the active session branch to the default branch.<br/><br/>Creates a `<code>CoreProposedChange</code>` in Infrahub so a human can review, approve,<br/>and merge the changes made during this session. The session branch remains<br/>active after calling this — you can continue making changes.<br/><br/>Parameters:<br/>    title: Title of the proposed change.<br/>    description: Optional description of the changes.<br/>    destination_branch: Target branch (default: resolved from Infrahub's default branch).<br/><br/>Returns:<br/>    Dict with proposed change id and branch details on success.</td>
            <td>
                <ul>
                    <li> <code>description</code> : string | null<br /></li>
                    <li> <code>destination_branch</code> : string | null<br /></li>
                    <li> <code>title</code> : string<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>6.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>query_graphql</b></code>
            </td>
            <td>Execute a GraphQL query against Infrahub.<br/><br/>To discover available kinds and their attributes, read the ``infrahub://schema``<br/>resource. If your client does not support MCP resources, call the `<code>get_schema</code>`<br/>tool instead. For the full GraphQL SDL, read ``infrahub://graphql-schema``.<br/><br/>Parameters:<br/>    query: GraphQL query to execute.<br/>    branch: Branch to execute the query against. Defaults to None (uses default branch).<br/><br/>Returns:<br/>    The result of the query.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                    <li> <code>query</code> : string<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>7.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>search_nodes</b></code>
            </td>
            <td>Search nodes of a specific kind by partial name match.<br/><br/>A convenience wrapper around get_nodes with ``partial_match=True`` and a `<code>name__value</code>`<br/>filter. Use when you need to find a node without knowing its exact name.<br/><br/>To discover available kinds, read the ``infrahub://schema`` resource.<br/>If your client does not support MCP resources, call the `<code>get_schema</code>` tool instead.<br/><br/>Args:<br/>    query: Partial name string to search for.<br/>    kind: Kind to search within.<br/>    branch: Branch to query.<br/>    limit: Maximum results (1-100, default 10).<br/><br/>Returns:<br/>    A list of matching node display labels.<br/><br/>Raises:<br/>    RuntimeError: Via `<code>_log_and_raise_error</code>` when the schema is not found or the query fails.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                    <li> <code>kind</code> : string<br /></li>
                    <li> <code>limit</code> : integer<br /></li>
                    <li> <code>query</code> : string<br /></li>
                </ul>
            </td>
        </tr>
</tbody>
</table>

## 📝 Prompts (4)

<table style="text-align: left;">
<thead>
    <tr>
        <th style="width: auto;"></th>
        <th style="width: auto;">Prompt Name</th>
        <th style="width: auto;">Description</th>
    </tr>
</thead>
<tbody style="vertical-align: top;">
        <tr>
            <td>1.</td>
            <td>
                <code><b>infrahub_agent</b></code>
            </td>
            <td>System prompt for the Infrahub infrastructure agent.</td>
        </tr>
        <tr>
            <td>2.</td>
            <td>
                <code><b>answer_infra_question</b></code>
            </td>
            <td>Read-only pipeline for answering infrastructure questions using Infrahub data.</td>
        </tr>
        <tr>
            <td>3.</td>
            <td>
                <code><b>make_infra_change</b></code>
            </td>
            <td>Write workflow for making infrastructure changes through Infrahub.</td>
        </tr>
        <tr>
            <td>4.</td>
            <td>
                <code><b>explore_schema</b></code>
            </td>
            <td>Schema discovery prompt for exploring Infrahub's data model.</td>
        </tr>
</tbody>
</table>

## 📄 Resources (3)

<table style="text-align: left;">
<thead>
    <tr>
        <th style="width: auto;"></th>
        <th style="width: auto;">Icon</th>
        <th style="width: auto;">Resource Name</th>
        <th style="width: auto;">Uri</th>
        <th style="width: auto;">Description</th>
    </tr>
</thead>
<tbody style="vertical-align: top;">
        <tr>
            <td>1.</td>
            <td>
              <!--- no icon -->
            </td>
            <td>
                <code><b>Schema Catalog</b></code>
            </td>
            <td>
                <a>infrahub://schema</a> <i>(application/json)</i>
            </td>
            <td>All non-internal schema kinds available in this Infrahub instance, as a JSON object mapping kind names to their human-readable labels. Use this to discover what kinds exist before calling get_nodes or node_upsert.</td>
        </tr>
        <tr>
            <td>2.</td>
            <td>
              <!--- no icon -->
            </td>
            <td>
                <code><b>GraphQL Schema</b></code>
            </td>
            <td>
                <a>infrahub://graphql-schema</a> <i>(text/plain)</i>
            </td>
            <td>Full GraphQL schema SDL for this Infrahub instance. Use as a reference when constructing complex query_graphql calls.</td>
        </tr>
        <tr>
            <td>3.</td>
            <td>
              <!--- no icon -->
            </td>
            <td>
                <code><b>Branches</b></code>
            </td>
            <td>
                <a>infrahub://branches</a> <i>(application/json)</i>
            </td>
            <td>All branches currently present in this Infrahub instance, including the active session branch when one has been created. Read this to know which branches are available before querying or proposing changes.</td>
        </tr>
</tbody>
</table>

## 🧩 Resource Templates (1)

<table style="text-align: left;">
<thead>
    <tr>
        <th style="width: auto;"></th>
        <th style="width: auto;">Icon</th>
        <th style="width: auto;">Name</th>
        <th style="width: auto;">Uri Template</th>
        <th style="width: auto;">Description</th>
    </tr>
</thead>
<tbody style="vertical-align: top;">
        <tr>
            <td>1.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>Schema Kind Detail</b></code>
            </td>
            <td>
                <a>infrahub://schema/{kind}</a> <i>(text/plain)</i>
            </td>
            <td>Full schema definition for a specific node kind: attributes, relationships, and the complete set of filters accepted by get_nodes. Fetch this before filtering nodes of an unfamiliar kind. Arrays are encoded in TOON tabular format: header declares fields once, each row is one entry.</td>
        </tr>
</tbody>
</table>

<sup>◾ generated by [mcp-discovery](https://github.com/rust-mcp-stack/mcp-discovery)</sup>
