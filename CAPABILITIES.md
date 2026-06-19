## Infrahub MCP Server 1.1.7

| ✔ Tools (10) | ✔ Prompts (4) | ✔ Resources (3) | ✔ Logging | ~~<span style="opacity:0.6" class="error">✘ Completions</span>~~ | ~~<span style="opacity:0.6" class="error">✘ Tasks</span>~~ |
| --- | --- | --- | --- | --- | --- |

## 🛠️ Tools (10)

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
            <td>List nodes of a specific kind — the default read path for typed queries with optional filtering and pagination.<br/><br/>Prefer this over `<code>query_graphql</code>` when you just need objects of one kind:<br/>results come back as display labels (fast, token-cheap) or full attribute<br/>dicts (``include_attributes=True``).<br/><br/>To discover available kinds, read the ``infrahub://schema`` resource.<br/>If your client does not support MCP resources, call the `<code>get_schema</code>` tool instead.<br/>To discover available filters for a kind, read ``infrahub://schema/{kind}``<br/>or call ``get_schema(kind='...')``.<br/><br/>Filter keys follow the schema's filter map. Attribute filters use<br/>``<attr>__value`` (e.g. ``{"name__value": "atl1"}``) and relationship<br/>filters chain via ``<rel>__<attr>__value`` (e.g.<br/>``{"site__name__value": "atl1"}``). See ``infrahub://schema/{kind}`` for<br/>the full list of valid keys.<br/><br/>Use `<code>offset</code>` and `<code>limit</code>` to page through large result sets. The response<br/>always includes `<code>total_count</code>` and `<code>has_more</code>` so you know when to stop.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                    <li> <code>filters</code> : unknown<br /></li>
                    <li> <code>include_attributes</code> : boolean<br /></li>
                    <li> <code>kind</code> : string<br /></li>
                    <li> <code>limit</code> : integer<br /></li>
                    <li> <code>offset</code> : integer<br /></li>
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
            <td>Discover available schema kinds — call this first when you don't know what kinds or filters exist.<br/><br/>Without a `<code>kind</code>`, returns the catalog of all kinds (compact JSON).<br/>With a `<code>kind</code>`, returns its attributes, relationships, and the full set<br/>of filter keys accepted by `<code>get_nodes</code>` (TOON-encoded for token efficiency).<br/><br/>Prefer reading the ``infrahub://schema`` resource if your client supports<br/>MCP resources — this tool provides the same data for clients that don't.</td>
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
                <code><b>get_session_info</b></code>
            </td>
            <td>Return the current MCP session state — call before writes to know which branch they target.<br/><br/>Reports the active session branch (if any) and the Infrahub instance address.<br/>A session branch is lazily auto-created on the first write tool call<br/>(`<code>node_upsert</code>` / `<code>node_delete</code>` / `<code>mutate_graphql</code>`) and is named<br/>``mcp/session-YYYYMMDD-<hex>``. Before that first write, `<code>session_branch</code>`<br/>is `<code>None</code>` and all read tools target the default branch.<br/><br/>Typical uses:<br/><br/>- Confirm which branch a proposed change would merge from.<br/>- Decide whether a write is about to open a new session branch.<br/>- Display the active branch to the user.<br/><br/>Returns:<br/>    Dict with `<code>session_branch</code>` (str or null), `<code>infrahub_address</code>`, and `<code>has_session_branch</code>`.</td>
            <td>
                <ul>
                </ul>
            </td>
        </tr>
        <tr>
            <td>4.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>mutate_graphql</b></code>
            </td>
            <td>Execute a GraphQL mutation against Infrahub — use only for complex writes that typed tools can't express.<br/><br/>Prefer `<code>node_upsert</code>` (create/update scalar attributes) or `<code>node_delete</code>`<br/>(remove a node) for straightforward changes; they validate against the<br/>schema and produce clearer audit entries. Reach for `<code>mutate_graphql</code>`<br/>when you need relationship edits, bulk operations, or any mutation shape<br/>not covered by the typed tools. For reads, use `<code>query_graphql</code>`.<br/><br/>The mutation always runs on the **active session branch** (auto-created on the<br/>first write of the session, ``mcp/session-YYYYMMDD-<hex>``). There is no branch<br/>override — writes are isolated to the session, and changes reach the default<br/>branch only through `<code>propose_changes</code>` and human review. To target a different<br/>branch deliberately, switch the session with `<code>reset_session_branch</code>` first.<br/>Branch- and schema-management mutations are rejected.<br/><br/>To discover available kinds and their attributes, read the ``infrahub://schema``<br/>resource or call the `<code>get_schema</code>` tool.<br/>For the full GraphQL SDL, read ``infrahub://graphql-schema``.</td>
            <td>
                <ul>
                    <li> <code>query</code> : string<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>5.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>node_delete</b></code>
            </td>
            <td>Delete a node in Infrahub on the active session branch.<br/><br/>The deletion is applied to the session branch only and is not visible on the<br/>default branch until a proposed change is merged.<br/>To discover available kinds, read the ``infrahub://schema`` resource.<br/>If your client does not support MCP resources, call the `<code>get_schema</code>`<br/>tool instead.</td>
            <td>
                <ul>
                    <li> <code>hfid</code> : string [ ] | null<br /></li>
                    <li> <code>id</code> : string | null<br /></li>
                    <li> <code>kind</code> : string<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>6.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>node_upsert</b></code>
            </td>
            <td>Create or update a node in Infrahub on the active session branch.<br/><br/>The session branch is auto-created on the first write of the session<br/>(``mcp/session-YYYYMMDD-<hex>``). Use `<code>propose_changes</code>` to open a<br/>review once your changes are ready.<br/>To discover available kinds and attributes, read the ``infrahub://schema``<br/>resource. If your client does not support MCP resources, call the<br/>`<code>get_schema</code>` tool instead.<br/><br/>- **Create**: omit both `<code>id</code>` and `<code>hfid</code>`.<br/>- **Update**: supply either `<code>id</code>` or `<code>hfid</code>` to identify the target node.<br/><br/>Only scalar attribute fields are accepted in `<code>data</code>`. To set relationship<br/>fields, use `<code>mutate_graphql</code>` with an appropriate GraphQL mutation.</td>
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
            <td>7.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>propose_changes</b></code>
            </td>
            <td>Open a proposed change (pull request) from the active session branch to the default branch.<br/><br/>Creates a `<code>CoreProposedChange</code>` in Infrahub so a human can review, approve,<br/>and merge the changes made during this session. The session branch remains<br/>active after calling this — you can continue making changes.</td>
            <td>
                <ul>
                    <li> <code>description</code> : string | null<br /></li>
                    <li> <code>destination_branch</code> : string | null<br /></li>
                    <li> <code>title</code> : string<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>8.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>query_graphql</b></code>
            </td>
            <td>Execute a read-only GraphQL query against Infrahub — use for reads only, never mutations.<br/><br/>Mutations are rejected at the AST level: use `<code>mutate_graphql</code>` instead<br/>(available when write mode is enabled). For simple attribute reads, prefer<br/>`<code>get_nodes</code>` / `<code>search_nodes</code>` — use GraphQL only when you need relationship<br/>traversal, aggregation, or fields not exposed by the typed tools.<br/><br/>To discover available kinds and their attributes, read the ``infrahub://schema``<br/>resource. If your client does not support MCP resources, call the `<code>get_schema</code>`<br/>tool instead. For the full GraphQL SDL, read ``infrahub://graphql-schema``.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                    <li> <code>query</code> : string<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>9.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>reset_session_branch</b></code>
            </td>
            <td>Reset or switch the active session branch for the current MCP session.<br/><br/>Use this to recover or take control of which branch your writes target:<br/><br/>- **No `<code>branch</code>`** — clears the cached session branch; the next write<br/>  auto-creates a fresh one. Useful after you have merged your work and want<br/>  to start a new change set.<br/>- **With `<code>branch</code>`** — points this session at the named branch. If it does<br/>  not exist and the name matches the configured branch pattern, it is created<br/>  and reported. The instance default branch and merged/read-only branches are<br/>  rejected.<br/><br/>Note: a merged or deleted session branch is recovered **automatically** on the<br/>next write — this tool is the explicit override on top of that.<br/><br/>Affects only the calling session; other sessions are unaffected.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>10.</td>
            <td>
                <!--- no icon -->
            </td>
            <td>
                <code><b>search_nodes</b></code>
            </td>
            <td>Find nodes of a specific kind by partial substring — use when you only know part of a value.<br/><br/>Matches the query as a substring against **all attributes** of the kind<br/>via Infrahub's `<code>any__value</code>` filter with ``partial_match=True``. Works<br/>uniformly on concrete kinds (e.g. `<code>LocationSite</code>`) and abstract/generic<br/>kinds (e.g. `<code>CoreNode</code>`) — agents can ping any kind without first<br/>checking whether it has a `<code>name</code>` attribute.<br/><br/>For a filter on one specific attribute (or combining multiple filters),<br/>use `<code>get_nodes</code>` with an explicit `<code>filters</code>` dict instead.<br/><br/>Each result is labelled with the node's `<code>display_label</code>` when present,<br/>falling back to its HFID (kind-prefixed) and finally its UUID — so<br/>generic-kind results that lack a `<code>display_label</code>` still return a<br/>human-readable identifier rather than a bare UUID.<br/><br/>To discover available kinds, read the ``infrahub://schema`` resource.<br/>If your client does not support MCP resources, call the `<code>get_schema</code>` tool instead.</td>
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
