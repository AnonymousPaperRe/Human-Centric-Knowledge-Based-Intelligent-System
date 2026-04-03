"""
Agent Chat Interface
"""
import streamlit as st
from agent import agent, context_manager
from services import memory_service, neo4j_service
from services.memory_service import get_full_conversation_history


INTENT_COLORS = {
    "specific":      "blue",
    "high_level":    "orange",
    "context_aware": "green",
}

# Source badge styling for working set entries: (label, color)
# ui_click is NOT in the working set — Tier 1 is always live from session state.
SOURCE_BADGE = {
    "ner":         ("NER",    "blue"),
    "tool_result": ("Graph",  "green"),
    "memory":      ("Memory", "gray"),
}

INSTANCE_LIMIT = 200


def render():
    st.header("KBS Agent Chat")

    col_chat, col_ctx = st.columns([2, 1])

    with col_ctx:
        _render_context_panel()

    with col_chat:
        _render_chat_panel()


# ── Right panel ───────────────────────────────────────────────────────────────

def _render_context_panel():
    # ── Tier 1: UI click ─────────────────────────────────────────────────────
    st.subheader("Context State")

    clicked = context_manager.get_clicked_entity()
    st.markdown("**Tier 1 — UI Selection**")
    if clicked:
        st.success(f"**{clicked['type']}** `{clicked['identifier']}`")
        props = clicked.get("properties", {})
        if props:
            with st.expander("Attributes", expanded=False):
                for k, v in props.items():
                    st.markdown(f"- **{k}**: `{v}`")
        if st.button("Clear", key="clear_entity"):
            context_manager.clear_clicked_entity()
            st.rerun()
    else:
        st.caption("No entity selected.")

    st.markdown("---")

    # ── Tier 3: Entity Working Set with TTL ──────────────────────────────────
    st.markdown("**Tier 3 — Entity Working Set**")
    wset = memory_service.get_entity_working_set(st.session_state)
    if wset:
        for e in wset:
            source = e.get("source", "memory")
            badge_label, badge_color = SOURCE_BADGE.get(source, ("?", "gray"))
            ttl = e.get("ttl", 0)
            # TTL bar: filled blocks
            ttl_bar = "█" * ttl + "░" * max(0, 5 - ttl)
            st.markdown(
                f":{badge_color}[**{badge_label}**] "
                f"`{e['label']}` · **{e['id']}**  \n"
                f"<small>{e.get('description', '')} &nbsp;|&nbsp; "
                f"TTL `{ttl_bar}` {ttl}</small>",
                unsafe_allow_html=True,
            )
        if st.button("Clear memory", key="clear_wset"):
            memory_service.clear_entity_working_set(st.session_state)
            st.rerun()
    else:
        st.caption("Working set empty.")

    st.markdown("---")
    st.subheader("Select Entity")
    _render_entity_selector()

    st.markdown("---")
    if st.button("Clear conversation", key="clear_conv"):
        memory_service.clear_conversation(st.session_state)
        st.rerun()


def _render_entity_selector():
    labels_r = neo4j_service.safe_run(
        "CALL db.labels() YIELD label RETURN label ORDER BY label"
    )
    all_labels = (
        [r["label"] for r in labels_r["data"]]
        if labels_r["ok"] and labels_r["data"]
        else ["PartSpec", "EquipmentSpec", "Vehicle", "ProductionProcess",
              "ChangeSet", "ChangeAction"]
    )

    entity_type = st.selectbox("Entity type", options=all_labels, key="agent_entity_type")

    if st.session_state.get("_agent_prev_type") != entity_type:
        st.session_state["_agent_prev_type"] = entity_type
        st.session_state["_agent_instances"] = None

    instances = st.session_state.get("_agent_instances")
    if instances is None:
        with st.spinner(f"Loading {entity_type}…"):
            r = neo4j_service.safe_run(
                f"MATCH (n:`{entity_type}`) RETURN properties(n) AS props "
                f"LIMIT {INSTANCE_LIMIT}"
            )
        if r["ok"]:
            st.session_state["_agent_instances"] = r["data"]
            instances = r["data"]
        else:
            st.error(r["error"])
            return

    if not instances:
        st.info(f"No `{entity_type}` nodes found.")
        return

    def _label(raw):
        p = raw.get("props") if isinstance(raw.get("props"), dict) else raw
        ident = (p.get("identifier") or p.get("name") or
                 p.get("sessionId") or p.get("title") or "—")
        extra = p.get("status") or p.get("changeType") or p.get("stateType") or ""
        return f"{ident}  [{extra}]" if extra else str(ident)

    option_labels = [_label(inst) for inst in instances]
    selected_label = st.selectbox(
        f"Instance ({len(instances)}{'+ ' if len(instances) == INSTANCE_LIMIT else ''} loaded)",
        options=option_labels,
        key="agent_instance_select",
    )

    idx = option_labels.index(selected_label)
    raw = instances[idx]
    current_props = raw.get("props") if isinstance(raw.get("props"), dict) else raw
    identifier = (
        current_props.get("identifier") or current_props.get("name") or
        current_props.get("sessionId") or current_props.get("title") or selected_label
    )

    if current_props:
        st.markdown("**Include in context:**")
        selected_attrs = {}
        for key in sorted(current_props.keys()):
            val = current_props[key]
            display = str(val)[:55] + ("…" if len(str(val)) > 55 else "")
            if st.checkbox(f"`{key}` = {display}", value=True, key=f"agent_attr_{key}"):
                selected_attrs[key] = val
    else:
        selected_attrs = {}

    if st.button("Set as context entity", type="primary", key="agent_set_entity"):
        context_manager.set_clicked_entity(entity_type, str(identifier), selected_attrs)
        memory_service.record_clicked_entity(
            st.session_state, entity_type, str(identifier), selected_attrs
        )
        st.rerun()


# ── Chat panel ────────────────────────────────────────────────────────────────

def _render_assistant_meta(meta: dict, user_input: str):
    """Render context + tools expanders for one assistant turn (history or live)."""
    intent           = meta.get("intent", "specific")
    rewritten        = meta.get("rewritten_question", user_input)
    tool_calls       = meta.get("tool_calls_made", [])
    reasoning        = meta.get("reasoning", "")
    ner_ctx          = meta.get("ner_context", {})
    working_set_snap = meta.get("working_set", [])

    color = INTENT_COLORS.get(intent, "gray")
    st.markdown(f":{color}[Intent: **{intent}**]")

    ner_pairs  = ner_ctx.get("node_instance_pairs", [])
    ner_labels = ner_ctx.get("node_labels", [])

    with st.expander("Context used for this query", expanded=False):
        if rewritten and rewritten != user_input:
            st.markdown("**Rewritten question:**")
            st.info(rewritten)
        else:
            st.caption("No rewrite needed — query was already unambiguous.")

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Tier 2 — NER entities extracted:**")
            if ner_pairs:
                for label, val, attr in ner_pairs:
                    badge = ":blue[NER]" if label != "Unknown" else ":red[Unknown]"
                    st.markdown(f"{badge} `{label}` · **{val}** ({attr})")
            if ner_labels:
                st.caption("Type hints:")
                for lbl, score in ner_labels:
                    st.markdown(f"- :orange[`{lbl}`] ({score:.0%})")
            if not ner_pairs and not ner_labels:
                st.caption("No entities extracted from query.")

        with col_b:
            st.markdown("**Entity working set after this turn:**")
            if working_set_snap:
                for e in working_set_snap:
                    src = e.get("source", "memory")
                    badge_lbl, badge_col = SOURCE_BADGE.get(src, ("?", "gray"))
                    st.markdown(
                        f":{badge_col}[{badge_lbl}] "
                        f"`{e['label']}` **{e['id']}** ttl={e['ttl']}"
                    )
            else:
                st.caption("Empty.")

    if tool_calls:
        with st.expander(f"Tools used ({len(tool_calls)})", expanded=False):
            for tc in tool_calls:
                st.markdown(f"**{tc['tool']}**")
                args = tc.get("args", {})
                if "query" in args:
                    st.code(args["query"], language="cypher")
                    other = {k: v for k, v in args.items() if k != "query"}
                    if other:
                        st.json(other)
                else:
                    st.json(args)
                st.text(f"Result: {tc.get('result_summary', '')[:300]}")

    if reasoning:
        with st.expander("Classification reasoning", expanded=False):
            st.text(reasoning)


def _render_chat_panel():
    # Chat input pinned at top of panel
    user_input = st.chat_input("Ask anything about the knowledge graph…")

    # ── Live turn (process immediately, before rendering history) ─────────────
    if user_input:
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                result = agent.chat(user_input, st.session_state)

            answer = result.get("answer", "")
            meta   = {
                "intent":             result.get("intent", "specific"),
                "rewritten_question": result.get("rewritten_question", user_input),
                "tool_calls_made":    result.get("tool_calls_made", []),
                "reasoning":          result.get("reasoning", ""),
                "ner_context":        result.get("ner_context", {}),
                "working_set":        result.get("working_set", []),
            }

            st.markdown(answer)
            _render_assistant_meta(meta, user_input)

        # Rerun so HITL buttons or updated history render cleanly
        st.rerun()

    # ── Conversation history (newest first) ───────────────────────────────────
    history = get_full_conversation_history(st.session_state)

    # Build ordered pairs then reverse so latest turn appears at top
    pairs: list[tuple] = []
    i = 0
    while i < len(history):
        msg = history[i]
        if (msg.get("role") == "user"
                and i + 1 < len(history)
                and history[i + 1].get("role") == "assistant"):
            pairs.append((msg, history[i + 1]))
            i += 2
        else:
            pairs.append((msg, None))
            i += 1

    pending = st.session_state.get("pending_confirmation")
    reversed_pairs = list(reversed(pairs))

    for idx, (user_msg, asst_msg) in enumerate(reversed_pairs):
        role = user_msg.get("role", "assistant")
        content = user_msg.get("content", "")
        if role == "user":
            with st.chat_message("user"):
                st.markdown(content)
            if asst_msg:
                with st.chat_message("assistant"):
                    st.markdown(asst_msg.get("content", ""))
                    meta = asst_msg.get("_meta")
                    if meta:
                        _render_assistant_meta(meta, content)
        else:
            with st.chat_message(role):
                st.markdown(content)
                meta = user_msg.get("_meta")
                if meta:
                    _render_assistant_meta(meta, "")

        # ── HITL confirmation block — rendered after the latest turn ──────────
        if idx == 0 and pending:
            ptype = pending.get("type", "")

            if ptype == "condition_confirmation":
                # ── Condition confirmation: editable time + property filters ──
                # Wrapped in st.form so ALL widget values (including text_input) are
                # committed to session_state on submit, even without pressing Enter first.
                st.warning("**Awaiting confirmation — Extracted conditions** (review and edit below):")

                TIME_OPS = [">=", "<=", ">", "<"]
                PROP_OPS = ["=", ">", "<", ">=", "<=", "CONTAINS", "STARTS WITH"]

                time_conds = pending.get("time_conditions") or []
                prop_conds = pending.get("property_conditions") or []

                with st.form("cond_confirm_form"):
                    edited_time: list[dict] = []
                    if time_conds:
                        st.markdown("**Temporal conditions**")
                    for i, tc in enumerate(time_conds):
                        with st.expander(
                            f"Time: {tc.get('label','')}.{tc.get('property','')} "
                            f"{tc.get('operator','')} '{tc.get('value','')}'",
                            expanded=True,
                        ):
                            c1, c2 = st.columns(2)
                            with c1:
                                lbl  = st.text_input("Label",    tc.get("label",""),    key=f"tc_lbl_{i}")
                                prop = st.text_input("Property", tc.get("property",""), key=f"tc_prop_{i}")
                            with c2:
                                op = st.selectbox(
                                    "Operator", TIME_OPS, key=f"tc_op_{i}",
                                    index=TIME_OPS.index(tc.get("operator",">=")) if tc.get("operator") in TIME_OPS else 0,
                                )
                                val = st.text_input("Value (YYYY-MM-DD HH:MM:SS)", tc.get("value",""), key=f"tc_val_{i}")
                            edited_time.append({"label": lbl, "property": prop, "operator": op, "value": val})

                    edited_props: list[dict] = []
                    if prop_conds:
                        st.markdown("**Property conditions**")
                    for i, pc in enumerate(prop_conds):
                        with st.expander(
                            f"Filter: {pc.get('label','')}.{pc.get('property','')} "
                            f"{pc.get('operator','')} '{pc.get('value','')}'",
                            expanded=True,
                        ):
                            c1, c2 = st.columns(2)
                            with c1:
                                lbl  = st.text_input("Label",    pc.get("label",""),    key=f"pc_lbl_{i}")
                                prop = st.text_input("Property", pc.get("property",""), key=f"pc_prop_{i}")
                            with c2:
                                op  = st.selectbox(
                                    "Operator", PROP_OPS, key=f"pc_op_{i}",
                                    index=PROP_OPS.index(pc.get("operator","=")) if pc.get("operator") in PROP_OPS else 0,
                                )
                                val = st.text_input("Value", pc.get("value",""), key=f"pc_val_{i}")
                            edited_props.append({"label": lbl, "property": prop,
                                                 "operator": op, "value": val})

                    col_yes, col_no = st.columns([1, 1])
                    with col_yes:
                        apply_clicked = st.form_submit_button("✓ Apply & Continue", type="primary")
                    with col_no:
                        cancel_clicked = st.form_submit_button("✗ Cancel (run without filter)")

                # Handle form submission outside the form block
                if apply_clicked:
                    st.session_state["pending_confirmation"]["confirmed_time_conditions"]     = edited_time
                    st.session_state["pending_confirmation"]["confirmed_property_conditions"] = edited_props
                    with st.spinner("Processing…"):
                        agent.handle_confirmation(True, st.session_state)
                    st.rerun()
                elif cancel_clicked:
                    with st.spinner("Processing…"):
                        agent.handle_confirmation(False, st.session_state)
                    st.rerun()

            elif ptype == "question_split":
                # ── Compound question split: per-sub-task logic + same sp field format ──
                sub_tasks_ui = pending.get("sub_tasks", [])
                st.warning(
                    f"**Awaiting confirmation — {len(sub_tasks_ui)} sub-questions detected** "
                    f"(review and edit below):"
                )

                _LOGIC_OPTIONS  = ["CHAIN (sequential)", "UNION (OR)", "INTERSECTION (AND)"]
                _LOGIC_OP_MAP   = {
                    "CHAIN (sequential)": "CHAIN",
                    "UNION (OR)": "OR",
                    "INTERSECTION (AND)": "AND",
                }
                _LOGIC_DISP_MAP = {
                    "CHAIN": "CHAIN (sequential)",
                    "OR":    "UNION (OR)",
                    "AND":   "INTERSECTION (AND)",
                }

                edited_sub_tasks_ui = []
                for _ti, _st_item in enumerate(sub_tasks_ui):
                    st.markdown(
                        f"**Sub-Task {_ti + 1} (Independent):** "
                        f"_{_st_item.get('question', '')}_"
                    )
                    _lop       = _st_item.get("logic_op")
                    _sub_probs_check = _st_item.get("sub_problems", [])

                    # Logic selector — show whenever there are 2+ sub-problems
                    if len(_sub_probs_check) > 1:
                        _default_disp = _LOGIC_DISP_MAP.get(_lop or "CHAIN", "CHAIN (sequential)")
                        _chosen = st.selectbox(
                            "Logic for linked items",
                            _LOGIC_OPTIONS,
                            index=_LOGIC_OPTIONS.index(_default_disp),
                            key=f"t{_ti}_logic",
                        )
                        _lop = _LOGIC_OP_MAP[_chosen]
                        st.caption(
                            "**CHAIN (sequential)**: step-by-step traversal  |  "
                            "**UNION (OR)**: match any source  |  "
                            "**INTERSECTION (AND)**: must match all sources"
                        )

                    # Sub-problems in same format as complex_decomposition
                    _sub_probs = _st_item.get("sub_problems", [])
                    _edited_sps_ti = []
                    for _si, _sp in enumerate(_sub_probs):
                        _sp_type     = _sp.get("type", "two_node")
                        _default_ind = _sp.get("independent", _sp_type == "one_node")
                        _header = (
                            f"Sub-problem {_sp.get('id', _si + 1)}: "
                            f"{_sp.get('description', '')}"
                        )
                        with st.expander(_header, expanded=True):
                            _independent = st.checkbox(
                                "Independent (look up separately, not combined with others)",
                                value=_default_ind,
                                key=f"t{_ti}_sp_ind_{_si}",
                            )
                            if _sp_type == "one_node":
                                _c1, _c2 = st.columns(2)
                                _lbl_a = _c1.text_input(
                                    "Label", _sp.get("label_a", ""),
                                    key=f"t{_ti}_sp_la_{_si}"
                                )
                                _id_a  = _c2.text_input(
                                    "ID",    _sp.get("id_a",    ""),
                                    key=f"t{_ti}_sp_ia_{_si}"
                                )
                                _edited_sps_ti.append({
                                    **_sp, "label_a": _lbl_a, "id_a": _id_a,
                                    "independent": _independent,
                                })
                            else:
                                _c1, _c2, _c3, _c4 = st.columns(4)
                                _lbl_a = _c1.text_input(
                                    "From label",        _sp.get("label_a", ""),
                                    key=f"t{_ti}_sp_la_{_si}"
                                )
                                _id_a  = _c2.text_input(
                                    "From ID",           _sp.get("id_a",    ""),
                                    key=f"t{_ti}_sp_ia_{_si}"
                                )
                                _lbl_b = _c3.text_input(
                                    "To label",          _sp.get("label_b", ""),
                                    key=f"t{_ti}_sp_lb_{_si}"
                                )
                                _id_b  = _c4.text_input(
                                    "To ID (empty=all)", _sp.get("id_b",    ""),
                                    key=f"t{_ti}_sp_ib_{_si}"
                                )
                                _edited_sps_ti.append({
                                    **_sp,
                                    "label_a": _lbl_a, "id_a": _id_a,
                                    "label_b": _lbl_b, "id_b": _id_b,
                                    "independent": _independent,
                                })

                    edited_sub_tasks_ui.append({
                        **_st_item,
                        "logic_op":     _lop,
                        "sub_problems": _edited_sps_ti,
                    })
                    st.divider()

                _col_yes_qs, _col_no_qs = st.columns([1, 1])
                with _col_yes_qs:
                    if st.button("✓ Confirm", type="primary", key="split_confirm"):
                        st.session_state["pending_confirmation"]["sub_tasks"] = [
                            _t for _t in edited_sub_tasks_ui if _t.get("question")
                        ]
                        with st.spinner("Processing…"):
                            agent.handle_confirmation(True, st.session_state)
                        st.rerun()
                with _col_no_qs:
                    if st.button("✗ Reject", key="split_reject"):
                        agent.handle_confirmation(False, st.session_state)
                        st.rerun()

            elif ptype == "complex_decomposition":
                # ── Scenario D: editable sub-problems + per-SP independent flag ──
                st.warning("**Awaiting confirmation — Query decomposition** (review and edit below):")

                sub_problems = pending.get("sub_problems", [])
                logic_tree   = pending.get("logic_tree", {})

                # Auto-detect initial pattern from the linked (non-independent) SPs.
                # one_node SPs default to independent so they don't distort detection.
                def _ui_detect_pattern(sps, tree):
                    linked = [s for s in sps if not s.get("independent", s.get("type") == "one_node")]
                    if not linked:
                        return "CHAIN"
                    def is_chain(s):
                        return len(s) > 1 and all(
                            s[i].get("label_b") == s[i + 1].get("label_a")
                            for i in range(len(s) - 1)
                        )
                    if is_chain(linked):
                        return "CHAIN"
                    return (tree or {}).get("op", "AND")

                # ── Render sub-problems first so checkboxes write to session_state,
                #    then read back to decide whether the pattern selector is needed.
                edited_sps = []
                for i, sp in enumerate(sub_problems):
                    sp_type = sp.get("type", "two_node")
                    default_ind = sp.get("independent", sp_type == "one_node")
                    header = f"Sub-problem {sp.get('id', i+1)}: {sp.get('description', '')}"
                    with st.expander(header, expanded=True):
                        independent = st.checkbox(
                            "Independent (look up separately, not combined with others)",
                            value=default_ind,
                            key=f"sp_ind_{i}",
                        )
                        if sp_type == "one_node":
                            c1, c2 = st.columns(2)
                            lbl_a = c1.text_input("Label", sp.get("label_a", ""), key=f"sp_la_{i}")
                            id_a  = c2.text_input("ID",    sp.get("id_a",    ""), key=f"sp_ia_{i}")
                            edited_sps.append({**sp, "label_a": lbl_a, "id_a": id_a,
                                               "independent": independent})
                        else:
                            c1, c2, c3, c4 = st.columns(4)
                            lbl_a = c1.text_input("From label",        sp.get("label_a", ""), key=f"sp_la_{i}")
                            id_a  = c2.text_input("From ID",           sp.get("id_a",    ""), key=f"sp_ia_{i}")
                            lbl_b = c3.text_input("To label",          sp.get("label_b", ""), key=f"sp_lb_{i}")
                            id_b  = c4.text_input("To ID (empty=all)", sp.get("id_b",    ""), key=f"sp_ib_{i}")
                            edited_sps.append({**sp, "label_a": lbl_a, "id_a": id_a,
                                               "label_b": lbl_b, "id_b": id_b,
                                               "independent": independent})

                # ── Pattern selector — only shown when at least one item is linked ──
                # Read live checkbox state from session_state (updated after each render).
                live_ind = [
                    st.session_state.get(f"sp_ind_{i}",
                        sp.get("independent", sp.get("type", "two_node") == "one_node"))
                    for i, sp in enumerate(sub_problems)
                ]
                all_independent = all(live_ind)

                if all_independent:
                    st.info("All items are marked **Independent** — each will be looked up separately. No linking logic needed.")
                    pattern = "INDEPENDENT"
                else:
                    LINKED_PATTERNS = ["CHAIN", "AND", "OR"]
                    init_pat = _ui_detect_pattern(sub_problems, logic_tree)
                    pattern  = st.selectbox(
                        "Logic for linked items",
                        LINKED_PATTERNS,
                        index=LINKED_PATTERNS.index(init_pat) if init_pat in LINKED_PATTERNS else 0,
                        key="decomp_pattern",
                    )
                    st.caption(
                        "**CHAIN**: A→B→C sequential  |  **AND**: intersection  |  **OR**: union  "
                        "— applies only to items **not** marked Independent above."
                    )

                col_yes, col_no = st.columns([1, 1])
                with col_yes:
                    if st.button("✓ Confirm", type="primary", key="decomp_confirm"):
                        st.session_state["pending_confirmation"]["sub_problems"]   = edited_sps
                        st.session_state["pending_confirmation"]["edited_pattern"] = pattern
                        with st.spinner("Processing…"):
                            agent.handle_confirmation(True, st.session_state)
                        st.rerun()
                with col_no:
                    if st.button("✗ Reject", key="decomp_reject"):
                        agent.handle_confirmation(False, st.session_state)
                        st.rerun()

            else:
                # ── Generic: relational_decomposition / independent_decomposition ─
                display_text = pending.get("description", "")
                st.warning(f"**Awaiting confirmation — Query plan:**\n\n> {display_text}")
                col_yes, col_no = st.columns([1, 1])
                with col_yes:
                    if st.button("✓ Confirm", type="primary", key="hitl_confirm"):
                        with st.spinner("Processing…"):
                            agent.handle_confirmation(True, st.session_state)
                        st.rerun()
                with col_no:
                    if st.button("✗ Reject", key="hitl_reject"):
                        agent.handle_confirmation(False, st.session_state)
                        st.rerun()
