"""
Page 3 — Cypher Template Management + Graph Primitives Management
"""
import streamlit as st
from services import template_service
from agent.graph_primitives import GRAPH_PRIMITIVES, load_custom_primitives


def render():
    st.header("Query Template Management")
    st.markdown(
        "Create, edit, and execute parameterized Cypher query templates "
        "stored in the knowledge graph."
    )

    tab_list, tab_create, tab_run, tab_primitives = st.tabs(
        ["Templates", "Create / Edit", "Run Template", "Graph Primitives"]
    )

    # ── Tab 1: List ───────────────────────────────────────────────────────────
    with tab_list:
        st.subheader("Stored Templates")
        if st.button("Refresh", key="refresh_templates"):
            pass  # force re-render

        templates = template_service.list_templates()
        if not templates:
            st.info("No templates yet. Create one in the 'Create / Edit' tab.")
        else:
            for tpl in templates:
                is_builtin = str(tpl.get("category", "")).startswith("builtin")
                with st.expander(f"**{tpl['name']}** [{tpl.get('category', 'general')}]"):
                    st.markdown(f"*{tpl.get('description', '')}*")
                    if is_builtin:
                        st.caption("Built-in template available to the agent and UI. Read-only in this page.")
                    st.code(tpl.get("cypher", ""), language="cypher")
                    params = tpl.get("params", [])
                    if params:
                        st.markdown(f"**Parameters**: {', '.join(params)}")
                    if is_builtin:
                        st.caption("To customize this query, create a new template with a different name.")
                    else:
                        col1, col2 = st.columns([1, 1])
                        with col1:
                            if st.button("Load into editor", key=f"load_{tpl['name']}"):
                                st.session_state["_edit_template"] = tpl
                                st.rerun()
                        with col2:
                            if st.button("Delete", key=f"del_{tpl['name']}"):
                                template_service.delete_template(tpl["name"])
                                st.success(f"Deleted '{tpl['name']}'.")
                                st.rerun()

    # ── Tab 2: Create / Edit ──────────────────────────────────────────────────
    with tab_create:
        edit_tpl = st.session_state.get("_edit_template", {})

        st.subheader("New Template" if not edit_tpl else f"Edit: {edit_tpl.get('name', '')}")

        with st.form("template_form"):
            name = st.text_input("Template name (unique)", value=edit_tpl.get("name", ""))
            description = st.text_input("Description", value=edit_tpl.get("description", ""))
            category = st.selectbox(
                "Category",
                options=["general", "specifications", "changes", "production", "logistics", "schema"],
                index=["general", "specifications", "changes", "production", "logistics", "schema"].index(
                    edit_tpl.get("category", "general")
                ) if edit_tpl.get("category") in ["general", "specifications", "changes", "production", "logistics", "schema"] else 0,
            )
            cypher = st.text_area(
                "Cypher template (use $param_name for parameters)",
                value=edit_tpl.get("cypher", ""),
                height=180,
                placeholder="MATCH (s:PartSpec {status: $status}) RETURN s.identifier LIMIT $limit",
            )
            params_str = st.text_input(
                "Parameter names (comma-separated)",
                value=", ".join(edit_tpl.get("params", [])) if edit_tpl.get("params") else "",
                placeholder="status, limit",
            )

            submitted = st.form_submit_button("Save Template", type="primary")

        if submitted:
            if not name.strip():
                st.error("Template name is required.")
            elif not cypher.strip():
                st.error("Cypher template is required.")
            else:
                param_list = [p.strip() for p in params_str.split(",") if p.strip()]
                template_service.create_template(
                    name=name.strip(),
                    description=description.strip(),
                    cypher_template=cypher.strip(),
                    param_names=param_list,
                    category=category,
                )
                st.success(f"Template '{name}' saved.")
                st.session_state.pop("_edit_template", None)
                st.rerun()

        if edit_tpl and st.button("Cancel editing"):
            st.session_state.pop("_edit_template", None)
            st.rerun()

    # ── Tab 3: Run ────────────────────────────────────────────────────────────
    with tab_run:
        st.subheader("Execute a Template")

        templates = template_service.list_templates()
        template_names = [t["name"] for t in templates]

        if not template_names:
            st.info("No templates available. Create one first.")
        else:
            selected = st.selectbox("Select template", options=template_names)

            if selected:
                tpl = template_service.get_template(selected)
                if tpl:
                    st.markdown(f"*{tpl.get('description', '')}*")
                    if str(tpl.get("category", "")).startswith("builtin"):
                        st.caption(f"Built-in template category: {tpl.get('category')}")
                    st.code(tpl.get("cypher", ""), language="cypher")

                    param_names = tpl.get("params", [])
                    param_values = {}
                    if param_names:
                        st.markdown("**Fill in parameters:**")
                        for pname in param_names:
                            param_values[pname] = st.text_input(
                                f"${pname}", key=f"param_{selected}_{pname}"
                            )

                    if st.button("Execute Template", type="primary"):
                        with st.spinner("Running…"):
                            result = template_service.execute_template(selected, param_values)
                        if result["ok"]:
                            data = result["data"]
                            st.success(f"Returned {len(data)} record(s).")
                            if data:
                                st.dataframe(data, use_container_width=True)
                            else:
                                st.info("No results returned.")
                        else:
                            st.error(f"Error: {result['error']}")

    # ── Tab 4: Graph Primitives ───────────────────────────────────────────────
    with tab_primitives:
        st.subheader("Graph Primitives")
        st.markdown(
            "Built-in deterministic Cypher traversal templates used by the agent. "
            "All built-in primitives filter by `{identifier: $a_id}` on the source node. "
            "Custom primitives are stored in Neo4j and merged at runtime."
        )

        prim_tab_view, prim_tab_add, prim_tab_custom = st.tabs(
            ["Browse Built-in", "Add Custom", "Manage Custom"]
        )

        # ── 4a: Browse built-in ───────────────────────────────────────────────
        with prim_tab_view:
            search_key = st.text_input(
                "Filter by key (e.g. Vehicle, Operation, Part)",
                key="prim_search",
                placeholder="Type a label name…",
            )

            # Group primitives by source label
            groups: dict[str, dict[str, str]] = {}
            for key, cypher in sorted(GRAPH_PRIMITIVES.items()):
                source = key.split("_to_")[0]
                groups.setdefault(source, {})[key] = cypher

            shown = 0
            for source, entries in groups.items():
                if search_key and search_key.lower() not in source.lower() and \
                        not any(search_key.lower() in k.lower() for k in entries):
                    continue
                with st.expander(f"**{source}** — {len(entries)} primitive(s)"):
                    for key, cypher in entries.items():
                        if search_key and search_key.lower() not in key.lower():
                            continue
                        st.markdown(f"`{key}`")
                        st.code(cypher, language="cypher")
                        shown += 1

            if not shown and search_key:
                st.info(f"No primitives match '{search_key}'.")
            elif not search_key:
                st.caption(f"Total built-in primitives: {len(GRAPH_PRIMITIVES)}")

        # ── 4b: Add custom primitive ──────────────────────────────────────────
        with prim_tab_add:
            st.markdown(
                "Custom primitives are stored as `RetrievalTemplate` nodes with "
                "`category='primitive'`. The key must follow the `LabelA_to_LabelB` pattern."
            )

            edit_prim = st.session_state.get("_edit_primitive", {})
            st.subheader("New Primitive" if not edit_prim else f"Edit: {edit_prim.get('name', '')}")

            with st.form("primitive_form"):
                prim_key = st.text_input(
                    "Key (format: LabelA_to_LabelB)",
                    value=edit_prim.get("name", ""),
                    placeholder="Part_to_WorkCell",
                )
                prim_desc = st.text_input(
                    "Description (optional)",
                    value=edit_prim.get("description", ""),
                )
                prim_cypher = st.text_area(
                    "Cypher — use $a_id for the source node identifier",
                    value=edit_prim.get("cypher", ""),
                    height=180,
                    placeholder=(
                        "MATCH (p:Part {identifier: $a_id})"
                        "-[:ASSEMBLED_IN]->(wc:WorkCell) "
                        "RETURN p AS Part, wc AS WorkCell"
                    ),
                )
                save_prim = st.form_submit_button("Save Primitive", type="primary")

            if save_prim:
                key_val = prim_key.strip()
                cypher_val = prim_cypher.strip()
                if not key_val:
                    st.error("Key is required.")
                elif "_to_" not in key_val:
                    st.error("Key must contain '_to_' (e.g. Part_to_WorkCell).")
                elif not cypher_val:
                    st.error("Cypher is required.")
                elif key_val in GRAPH_PRIMITIVES:
                    st.error(
                        f"'{key_val}' already exists as a built-in primitive and cannot be overridden here."
                    )
                else:
                    template_service.create_template(
                        name=key_val,
                        description=prim_desc.strip(),
                        cypher_template=cypher_val,
                        param_names=["a_id"],
                        category="primitive",
                    )
                    load_custom_primitives()
                    st.success(f"Custom primitive '{key_val}' saved and registered.")
                    st.session_state.pop("_edit_primitive", None)
                    st.rerun()

            if edit_prim and st.button("Cancel", key="cancel_prim_edit"):
                st.session_state.pop("_edit_primitive", None)
                st.rerun()

        # ── 4c: Manage custom primitives ──────────────────────────────────────
        with prim_tab_custom:
            st.subheader("Custom Primitives (stored in Neo4j)")

            if st.button("Refresh", key="refresh_primitives"):
                load_custom_primitives()

            custom_prims = [
                t for t in template_service.list_templates()
                if t.get("category") == "primitive"
            ]

            if not custom_prims:
                st.info("No custom primitives yet. Add one in the 'Add Custom' tab.")
            else:
                for prim in custom_prims:
                    with st.expander(f"`{prim['name']}`"):
                        st.markdown(f"*{prim.get('description', '')}*")
                        st.code(prim.get("cypher", ""), language="cypher")
                        col1, col2 = st.columns([1, 1])
                        with col1:
                            if st.button("Edit", key=f"edit_prim_{prim['name']}"):
                                st.session_state["_edit_primitive"] = prim
                                st.rerun()
                        with col2:
                            if st.button("Delete", key=f"del_prim_{prim['name']}"):
                                template_service.delete_template(prim["name"])
                                load_custom_primitives()
                                st.success(f"Deleted '{prim['name']}'.")
                                st.rerun()
