## Infrahub MCP Server 0.1.2

| Tools (6) | Prompts (4) | Resources (4) |
| --- | --- | --- |

## Tools (6)

<table style="text-align: left;">
<thead>
    <tr>
        <th style="width: auto;"></th>
        <th style="width: auto;">Tool Name</th>
        <th style="width: auto;">Description</th>
        <th style="width: auto;">Inputs</th>
    </tr>
</thead>
<tbody style="vertical-align: top;">
        <tr>
            <td>1.</td>
            <td>
                <code><b>get_nodes</b></code>
            </td>
            <td>Retrieve objects of a specific kind from Infrahub. Supports attribute/relationship filters, partial matching, and optional full attribute output in TOON tabular format.<br/><br/>Tags: <code>nodes</code>, <code>retrieve</code><br/>Read-only: yes</td>
            <td>
                <ul>
                    <li><code>kind</code> : string — Kind of the objects to retrieve.</li>
                    <li><code>branch</code> : string | null — Branch to query. Defaults to the default branch.</li>
                    <li><code>filters</code> : object | null — Attribute/relationship filters. See <code>infrahub://schema/{kind}</code> for the full filter map.</li>
                    <li><code>partial_match</code> : boolean (default false) — Use partial (substring) matching for string filters.</li>
                    <li><code>include_attributes</code> : boolean (default false) — Return full attribute values in TOON tabular format instead of just display labels.</li>
                    <li><code>limit</code> : integer (default 50, -1 for all) — Maximum nodes to return.</li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>2.</td>
            <td>
                <code><b>search_nodes</b></code>
            </td>
            <td>Search nodes of a specific kind by partial name match. A convenience wrapper around <code>get_nodes</code> with <code>partial_match=True</code> and a <code>name__value</code> filter.<br/><br/>Tags: <code>nodes</code>, <code>search</code><br/>Read-only: yes</td>
            <td>
                <ul>
                    <li><code>query</code> : string (min length 1) — Partial name/label to search for.</li>
                    <li><code>kind</code> : string — Kind to search within.</li>
                    <li><code>branch</code> : string | null — Branch to query. Defaults to the default branch.</li>
                    <li><code>limit</code> : integer (default 10, 1-100) — Maximum number of results to return.</li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>3.</td>
            <td>
                <code><b>query_graphql</b></code>
            </td>
            <td>Execute a GraphQL query or mutation against Infrahub.<br/><br/>Tags: <code>graphql</code>, <code>retrieve</code><br/>Read-only: no</td>
            <td>
                <ul>
                    <li><code>query</code> : string — GraphQL query to execute.</li>
                    <li><code>branch</code> : string | null — Branch to execute the query against. Defaults to the default branch.</li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>4.</td>
            <td>
                <code><b>node_upsert</b></code>
            </td>
            <td>Create or update a node in Infrahub on the active session branch. Omit both <code>id</code> and <code>hfid</code> to create; supply one to update. Only scalar attributes are accepted in <code>data</code>; use <code>query_graphql</code> for relationship mutations.<br/><br/>Tags: <code>nodes</code>, <code>write</code><br/>Read-only: no, Destructive: no</td>
            <td>
                <ul>
                    <li><code>kind</code> : string — Kind of the node to create or update.</li>
                    <li><code>data</code> : object — Flat {attribute: value} map.</li>
                    <li><code>id</code> : string | null — UUID of an existing node to update.</li>
                    <li><code>hfid</code> : array of strings | null — Human-friendly ID of an existing node to update.</li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>5.</td>
            <td>
                <code><b>node_delete</b></code>
            </td>
            <td>Delete a node in Infrahub on the active session branch. The deletion is not visible on the default branch until a proposed change is merged.<br/><br/>Tags: <code>nodes</code>, <code>write</code><br/>Read-only: no, Destructive: yes</td>
            <td>
                <ul>
                    <li><code>kind</code> : string — Kind of the node to delete.</li>
                    <li><code>id</code> : string | null — UUID of the node to delete.</li>
                    <li><code>hfid</code> : array of strings | null — Human-friendly ID of the node to delete.</li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>6.</td>
            <td>
                <code><b>propose_changes</b></code>
            </td>
            <td>Open a proposed change (pull request) from the active session branch to the default branch for human review. The session branch remains active after calling this.<br/><br/>Tags: <code>branches</code>, <code>write</code><br/>Read-only: no, Destructive: no</td>
            <td>
                <ul>
                    <li><code>title</code> : string — Title for the proposed change.</li>
                    <li><code>description</code> : string | null — Optional description explaining the motivation for the changes.</li>
                    <li><code>destination_branch</code> : string | null — Branch to merge into. Defaults to the instance's default branch.</li>
                </ul>
            </td>
        </tr>
</tbody>
</table>

## Resources (4)

<table style="text-align: left;">
<thead>
    <tr>
        <th style="width: auto;"></th>
        <th style="width: auto;">URI Pattern</th>
        <th style="width: auto;">Name</th>
        <th style="width: auto;">Description</th>
    </tr>
</thead>
<tbody style="vertical-align: top;">
        <tr>
            <td>1.</td>
            <td><code>infrahub://schema</code></td>
            <td>Schema Catalog</td>
            <td>All non-internal schema kinds available in this Infrahub instance, as a JSON object mapping kind names to their human-readable labels. Use this to discover what kinds exist before calling <code>get_nodes</code> or <code>node_upsert</code>.<br/><br/>MIME type: <code>application/json</code></td>
        </tr>
        <tr>
            <td>2.</td>
            <td><code>infrahub://schema/{kind}</code></td>
            <td>Schema Kind Detail</td>
            <td>Full schema definition for a specific node kind: attributes, relationships, and the complete set of filters accepted by <code>get_nodes</code>. Arrays are encoded in TOON tabular format.<br/><br/>MIME type: <code>text/plain</code></td>
        </tr>
        <tr>
            <td>3.</td>
            <td><code>infrahub://graphql-schema</code></td>
            <td>GraphQL Schema</td>
            <td>Full GraphQL schema SDL for this Infrahub instance. Use as a reference when constructing complex <code>query_graphql</code> calls.<br/><br/>MIME type: <code>text/plain</code></td>
        </tr>
        <tr>
            <td>4.</td>
            <td><code>infrahub://branches</code></td>
            <td>Branches</td>
            <td>All branches currently present in this Infrahub instance, including the active session branch when one has been created. Read this to know which branches are available before querying or proposing changes.<br/><br/>MIME type: <code>application/json</code></td>
        </tr>
</tbody>
</table>

## Prompts (4)

<table style="text-align: left;">
<thead>
    <tr>
        <th style="width: auto;"></th>
        <th style="width: auto;">Prompt Name</th>
        <th style="width: auto;">Description</th>
        <th style="width: auto;">Parameters</th>
    </tr>
</thead>
<tbody style="vertical-align: top;">
        <tr>
            <td>1.</td>
            <td><code><b>infrahub_agent</b></code></td>
            <td>System prompt for the Infrahub infrastructure agent. Provides a complete operating guide including available resources, tools, branch-per-session workflow, and safety rules.</td>
            <td><em>None</em></td>
        </tr>
        <tr>
            <td>2.</td>
            <td><code><b>answer_infra_question</b></code></td>
            <td>Read-only pipeline for answering infrastructure questions using Infrahub data. Guides the agent through kind discovery, schema reading, data retrieval, relationship traversal, and answer formatting.</td>
            <td>
                <ul>
                    <li><code>question</code> : string — The infrastructure question to answer.</li>
                    <li><code>kind_hint</code> : string | null — Known or guessed schema kind. Skips the discovery step if provided.</li>
                    <li><code>fields</code> : string | null — Comma-separated attribute names to include in the result.</li>
                    <li><code>branch</code> : string | null — Branch to query.</li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>3.</td>
            <td><code><b>make_infra_change</b></code></td>
            <td>Write workflow for making infrastructure changes through Infrahub. Guides the agent through schema validation, applying changes via <code>node_upsert</code>/<code>node_delete</code>, verification, and proposing changes for review.</td>
            <td>
                <ul>
                    <li><code>description</code> : string — What infrastructure change to make.</li>
                    <li><code>kind</code> : string | null — Target schema kind for the change.</li>
                    <li><code>branch</code> : string | null — Existing branch to target.</li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>4.</td>
            <td><code><b>explore_schema</b></code></td>
            <td>Schema discovery prompt for exploring Infrahub's data model. Guides the agent through reading the schema catalog or a specific kind's full definition including attributes, relationships, and filters.</td>
            <td>
                <ul>
                    <li><code>kind</code> : string | null — Specific kind to explore. Omit to browse the full catalog.</li>
                </ul>
            </td>
        </tr>
</tbody>
</table>
