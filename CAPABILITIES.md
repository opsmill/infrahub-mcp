## Infrahub MCP Server 0.1.0
| 🟢 Tools (10) | 🟢 Prompts | 🟢 Resources | <span style="opacity:0.6">🔴 Logging</span> | 🟢 Experimental |
| --- | --- | --- | --- | --- |
## 🛠️ Tools (10)

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
                <code><b>branch_create</b></code>
            </td>
            <td>Create a new branch in infrahub.<br/><br/>Parameters:<br/>    name: Name of the branch to create.<br/>    sync_with_git: Whether to sync the branch with git. Defaults to False.<br/><br/>Returns:<br/>    Dictionary with success status and branch details.</td>
            <td>
                <ul>
                    <li> <code>name</code> : string<br /></li>
                    <li> <code>sync_with_git</code> : boolean<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>2.</td>
            <td>
                <code><b>get_branches</b></code>
            </td>
            <td>Retrieve all branches from infrahub.</td>
            <td>
                <ul>
                </ul>
            </td>
        </tr>
        <tr>
            <td>3.</td>
            <td>
                <code><b>get_graphql_schema</b></code>
            </td>
            <td>Retrieve the GraphQL schema from Infrahub<br/><br/>Parameters:<br/>    None<br/><br/>Returns:<br/>    MCPResponse with the GraphQL schema as a string.</td>
            <td>
                <ul>
                </ul>
            </td>
        </tr>
        <tr>
            <td>4.</td>
            <td>
                <code><b>get_node_filters</b></code>
            </td>
            <td>Retrieve all the available filters for a specific schema node kind.<br/><br/>There's multiple types of filters<br/>attribute filters are in the form attribute__value<br/><br/>relationship filters are in the form relationship__attribute__value<br/>you can find more information on the peer node of the relationship using the <code>get_schema</code> tool<br/><br/>Filters that start with parent refer to a related generic schema node.<br/>You can find the type of that related node by inspected the output of the <code>get_schema</code> tool.<br/><br/>Parameters:<br/>    kind: Kind of the objects to retrieve.<br/>    branch: Branch to retrieve the objects from. Defaults to None (uses default branch).<br/><br/>Returns:<br/>    MCPResponse with success status and filters.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                    <li> <code>kind</code> : string<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>5.</td>
            <td>
                <code><b>get_nodes</b></code>
            </td>
            <td>Get all objects of a specific kind from Infrahub.<br/><br/>To retrieve the list of available kinds, use the <code>get_schema_mapping</code> tool.<br/>To retrieve the list of available filters for a specific kind, use the <code>get_node_filters</code> tool.<br/><br/>Parameters:<br/>    kind: Kind of the objects to retrieve.<br/>    branch: Branch to retrieve the objects from. Defaults to None (uses default branch).<br/>    filters: Dictionary of filters to apply.<br/>    partial_match: Whether to use partial matching for filters.<br/><br/>Returns:<br/>    MCPResponse with success status and objects.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                    <li> <code>filters</code> : unknown<br /></li>
                    <li> <code>kind</code> : string<br /></li>
                    <li> <code>partial_match</code> : boolean<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>6.</td>
            <td>
                <code><b>get_related_nodes</b></code>
            </td>
            <td>Retrieve related nodes by relation name and a kind.<br/><br/>Args:<br/>    kind: Kind of the node to fetch.<br/>    filters: Filters to apply on the node to fetch.<br/>    relation: Name of the relation to fetch.<br/>    branch: Branch to fetch the node from. Defaults to None (uses default branch).<br/><br/>Returns:<br/>    MCPResponse with success status and objects.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                    <li> <code>filters</code> : unknown<br /></li>
                    <li> <code>kind</code> : string<br /></li>
                    <li> <code>relation</code> : string<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>7.</td>
            <td>
                <code><b>get_schema</b></code>
            </td>
            <td>Retrieve the full schema for a specific kind.<br/>This includes attributes, relationships, and their types.<br/><br/>Parameters:<br/>    kind: Schema Kind to retrieve.<br/>    branch: Branch to retrieve the schema from. Defaults to None (uses default branch).<br/><br/>Returns:<br/>    Dictionary with success status and schema.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                    <li> <code>kind</code> : string<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>8.</td>
            <td>
                <code><b>get_schema_mapping</b></code>
            </td>
            <td>List all schema nodes and generics available in Infrahub<br/><br/>Parameters:<br/>    branch: Branch to retrieve the mapping from. Defaults to None (uses default branch).<br/><br/>Returns:<br/>    Dictionary with success status and schema mapping.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>9.</td>
            <td>
                <code><b>get_schemas</b></code>
            </td>
            <td>Retrieve all schemas from Infrahub, optionally excluding Profiles and Templates.<br/><br/>Parameters:<br/>    infrahub_client: Infrahub client to use<br/>    branch: Branch to retrieve schemas from<br/>    exclude_profiles: Whether to exclude Profile schemas. Defaults to True.<br/>    exclude_templates: Whether to exclude Template schemas. Defaults to True.<br/><br/>Returns:<br/>    Dictionary with success status and schemas.</td>
            <td>
                <ul>
                    <li> <code>branch</code> : string | null<br /></li>
                    <li> <code>exclude_profiles</code> : boolean<br /></li>
                    <li> <code>exclude_templates</code> : boolean<br /></li>
                </ul>
            </td>
        </tr>
        <tr>
            <td>10.</td>
            <td>
                <code><b>query_graphql</b></code>
            </td>
            <td>Execute a GraphQL query against Infrahub.<br/><br/>Parameters:<br/>    query: GraphQL query to execute.<br/><br/>Returns:<br/>    MCPResponse with the result of the query.</td>
            <td>
                <ul>
                    <li> <code>query</code> : string<br /></li>
                </ul>
            </td>
        </tr>
</tbody>
</table>
