"""Page for managing tournaments: tournaments, teams, groups and matches."""
import math
from datetime import date
import sys
from pathlib import Path

import streamlit as st

# Add parent directory to path to import utils
sys.path.append(str(Path(__file__).parent.parent))
from utils import (
    get_supabase_client,
    fetch_courts,
    court_label,
    fetch_tournaments,
    fetch_profiles,
    tournament_label,
    team_label,
    profile_label,
)

st.set_page_config(page_title="Torneios", layout="wide", page_icon="🏆")

# Check authentication
if not st.session_state.get("authentication_status"):
    st.error("Fazer login primeiro.")
    st.stop()

st.title("🏆 Torneios")
st.caption("ATENÇÃO: qualquer alteração feita aqui é visível na aplicação.")

sb = get_supabase_client()

FORMATS = {
    "knockout": "Eliminatória direta",
    "group_then_knockout": "Fase de grupos + Eliminatória",
}
STATUSES = ["draft", "registration", "group_stage", "knockout", "completed", "cancelled"]
MATCH_STATUSES = ["scheduled", "in_progress", "completed", "cancelled"]


# -----------------------
# Helpers (local)
# -----------------------
def fetch_teams(tournament_id):
    res = (
        sb.table("tournament_teams")
        .select("*")
        .eq("tournament_id", tournament_id)
        .order("name")
        .execute()
    )
    return res.data or []


def fetch_groups(tournament_id):
    res = (
        sb.table("tournament_groups")
        .select("*")
        .eq("tournament_id", tournament_id)
        .order("name")
        .execute()
    )
    return res.data or []


def fetch_matches(tournament_id):
    res = (
        sb.table("tournament_matches")
        .select("*")
        .eq("tournament_id", tournament_id)
        .order("stage")
        .order("round")
        .order("bracket_position")
        .execute()
    )
    return res.data or []


def tournament_selectbox(key, label="Torneio *"):
    """Render a tournament selectbox and return the selected tournament dict (or None)."""
    tournaments = fetch_tournaments(sb)
    if not tournaments:
        st.warning("Ainda não existem torneios. Cria um no separador **Torneios**.")
        return None
    labels = [tournament_label(t) for t in tournaments]
    label_to_t = {tournament_label(t): t for t in tournaments}
    selected = st.selectbox(label, labels, key=key)
    return label_to_t[selected]


def round_label_for(num_matches: int) -> str:
    """Human label for a knockout round given how many matches it has."""
    return {
        1: "Final",
        2: "Meias-finais",
        4: "Quartos de final",
        8: "Oitavos de final",
        16: "Dezasseis-avos",
    }.get(num_matches, f"Ronda de {num_matches} jogos")


def date_or_none(s):
    """Parse a 'YYYY-MM-DD' string into a date, or None."""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def advance_winner(sb, match, winner_id):
    """Push the winner of a knockout match into the correct slot of its next match."""
    nm_id = match.get("next_match_id")
    if not nm_id:
        return
    # feeders at even bracket positions fill team_a, odd fill team_b
    slot = "team_a_id" if (match.get("bracket_position") or 0) % 2 == 0 else "team_b_id"
    sb.table("tournament_matches").update({slot: winner_id}).eq("id", nm_id).execute()


def generate_bracket(sb, tournament, team_ids):
    """Create a single-elimination bracket. Extra teams beyond a power of two get byes.

    Returns the number of matches created.
    """
    n = len(team_ids)
    size = 1
    while size < n:
        size *= 2
    rounds = int(math.log2(size))
    slots = list(team_ids) + [None] * (size - n)
    admin = st.session_state.get("username")

    # 1) create empty matches, round by round (round 1 = first round, last = final)
    round_match_ids = {}
    created = 0
    for r in range(1, rounds + 1):
        num = size // (2 ** r)
        label = round_label_for(num)
        ids = []
        for pos in range(num):
            res = sb.table("tournament_matches").insert({
                "tournament_id": tournament["id"],
                "stage": "knockout",
                "round": r,
                "round_label": label,
                "bracket_position": pos,
                "court_id": tournament.get("court_id"),
                "status": "scheduled",
                "admin_created_by": admin,
            }).execute()
            ids.append(res.data[0]["id"])
            created += 1
        round_match_ids[r] = ids

    # 2) link each match to the next round's match
    for r in range(1, rounds):
        for pos, mid in enumerate(round_match_ids[r]):
            sb.table("tournament_matches").update(
                {"next_match_id": round_match_ids[r + 1][pos // 2]}
            ).eq("id", mid).execute()

    # 3) seat teams into round 1, auto-resolving byes
    for pos, mid in enumerate(round_match_ids[1]):
        a, b = slots[2 * pos], slots[2 * pos + 1]
        update = {"team_a_id": a, "team_b_id": b}
        if (a is None) ^ (b is None):  # exactly one team -> bye
            winner = a or b
            update["winner_team_id"] = winner
            update["status"] = "completed"
            if rounds >= 2:
                nxt = round_match_ids[2][pos // 2]
                slot = "team_a_id" if pos % 2 == 0 else "team_b_id"
                sb.table("tournament_matches").update({slot: winner}).eq("id", nxt).execute()
        sb.table("tournament_matches").update(update).eq("id", mid).execute()

    return created


# =======================================================================
# TABS
# =======================================================================
tab_t, tab_e, tab_g, tab_j = st.tabs(
    ["🏆 Torneios", "👥 Equipas", "🔀 Grupos & Sorteio", "🏀 Jogos"]
)

# =======================================================================
# TAB 1: Tournaments (create / edit)
# =======================================================================
with tab_t:
    sub_create, sub_edit = st.tabs(["Criar", "Editar"])

    courts = fetch_courts(sb)
    court_labels = ["— Sem campo —"] + [court_label(c) for c in courts]
    court_label_to_id = {court_label(c): c["id"] for c in courts}

    # ---- Create ----
    with sub_create:
        st.subheader("Criar Torneio")
        with st.form("create_tournament_form"):
            col1, col2 = st.columns(2)
            with col1:
                name_in = st.text_input("Nome *")
                fmt_in = st.selectbox(
                    "Formato *",
                    list(FORMATS.keys()),
                    format_func=lambda k: FORMATS[k],
                )
                team_size_in = st.number_input(
                    "Tamanho da equipa (1 = 1x1, 3 = 3x3, …) *", 1, 15, 5, step=1
                )
                court_sel = st.selectbox("Campo", court_labels, key="create_t_court")
            with col2:
                status_in = st.selectbox("Estado *", STATUSES, index=0)
                max_teams_in = st.number_input(
                    "Máx. equipas (0 = sem limite)", 0, 256, 0, step=1
                )
                start_in = st.date_input("Data de início", value=None)
                end_in = st.date_input("Data de fim", value=None)

            desc_in = st.text_area("Descrição")

            st.markdown("**Configuração da fase de grupos** (só para o formato com grupos)")
            gc1, gc2, gc3, gc4 = st.columns(4)
            with gc1:
                pts_win = st.number_input("Pontos vitória", 0, 10, 2, step=1)
            with gc2:
                pts_draw = st.number_input("Pontos empate", 0, 10, 1, step=1)
            with gc3:
                pts_loss = st.number_input("Pontos derrota", 0, 10, 1, step=1)
            with gc4:
                advancing = st.number_input("Apuram por grupo", 1, 16, 2, step=1)

            submitted = st.form_submit_button("Criar Torneio")

        if submitted:
            if not name_in.strip():
                st.error("Nome é obrigatório.")
                st.stop()

            payload = {
                "name": name_in.strip(),
                "description": desc_in.strip() or None,
                "format": fmt_in,
                "team_size": int(team_size_in),
                "status": status_in,
                "max_teams": int(max_teams_in) or None,
                "start_date": start_in.isoformat() if start_in else None,
                "end_date": end_in.isoformat() if end_in else None,
                "points_win": int(pts_win),
                "points_draw": int(pts_draw),
                "points_loss": int(pts_loss),
                "teams_advancing_per_group": int(advancing),
                "court_id": court_label_to_id.get(court_sel),
                "admin_created_by": st.session_state.get("username"),
            }
            try:
                res = sb.table("tournaments").insert(payload).execute()
                st.success(f"Torneio criado ✅ (ID: {res.data[0]['id']})")
            except Exception as e:
                st.error(f"Erro ao criar torneio: {e}")

    # ---- Edit ----
    with sub_edit:
        st.subheader("Editar Torneio")
        t = tournament_selectbox("edit_t_select")
        if t:
            st.info(f"A editar: **{t['name']}** (ID: {t['id']})")
            with st.form("edit_tournament_form"):
                col1, col2 = st.columns(2)
                with col1:
                    name_e = st.text_input("Nome *", value=t.get("name", ""))
                    fmt_e = st.selectbox(
                        "Formato *",
                        list(FORMATS.keys()),
                        index=list(FORMATS.keys()).index(t.get("format", "knockout")),
                        format_func=lambda k: FORMATS[k],
                    )
                    team_size_e = st.number_input(
                        "Tamanho da equipa *", 1, 15, int(t.get("team_size") or 5), step=1
                    )
                    cur_court = next(
                        (court_label(c) for c in courts if c["id"] == t.get("court_id")),
                        "— Sem campo —",
                    )
                    court_e = st.selectbox(
                        "Campo", court_labels,
                        index=court_labels.index(cur_court),
                        key="edit_t_court",
                    )
                with col2:
                    status_e = st.selectbox(
                        "Estado *", STATUSES, index=STATUSES.index(t.get("status", "draft"))
                    )
                    max_teams_e = st.number_input(
                        "Máx. equipas (0 = sem limite)", 0, 256,
                        int(t.get("max_teams") or 0), step=1
                    )
                    start_e = st.date_input(
                        "Data de início",
                        value=date_or_none(t.get("start_date")),
                    )
                    end_e = st.date_input(
                        "Data de fim",
                        value=date_or_none(t.get("end_date")),
                    )

                desc_e = st.text_area("Descrição", value=t.get("description", "") or "")

                gc1, gc2, gc3, gc4 = st.columns(4)
                with gc1:
                    pts_win_e = st.number_input("Pontos vitória", 0, 10, int(t.get("points_win") or 2), step=1)
                with gc2:
                    pts_draw_e = st.number_input("Pontos empate", 0, 10, int(t.get("points_draw") or 1), step=1)
                with gc3:
                    pts_loss_e = st.number_input("Pontos derrota", 0, 10, int(t.get("points_loss") or 1), step=1)
                with gc4:
                    advancing_e = st.number_input("Apuram por grupo", 1, 16, int(t.get("teams_advancing_per_group") or 2), step=1)

                submitted_e = st.form_submit_button("Atualizar Torneio")

            if submitted_e:
                if not name_e.strip():
                    st.error("Nome é obrigatório.")
                    st.stop()
                payload = {
                    "name": name_e.strip(),
                    "description": desc_e.strip() or None,
                    "format": fmt_e,
                    "team_size": int(team_size_e),
                    "status": status_e,
                    "max_teams": int(max_teams_e) or None,
                    "start_date": start_e.isoformat() if start_e else None,
                    "end_date": end_e.isoformat() if end_e else None,
                    "points_win": int(pts_win_e),
                    "points_draw": int(pts_draw_e),
                    "points_loss": int(pts_loss_e),
                    "teams_advancing_per_group": int(advancing_e),
                    "court_id": court_label_to_id.get(court_e),
                    "admin_created_by": st.session_state.get("username"),
                }
                try:
                    sb.table("tournaments").update(payload).eq("id", t["id"]).execute()
                    st.success("Torneio atualizado ✅")
                except Exception as e:
                    st.error(f"Erro ao atualizar torneio: {e}")

            st.divider()
            if st.button("🗑️ Eliminar torneio", type="secondary", key="del_t"):
                try:
                    sb.table("tournaments").delete().eq("id", t["id"]).execute()
                    st.success("Torneio eliminado. Recarrega a página.")
                except Exception as e:
                    st.error(f"Erro ao eliminar: {e}")

# =======================================================================
# TAB 2: Teams & rosters
# =======================================================================
with tab_e:
    st.subheader("Equipas & Plantéis")
    t = tournament_selectbox("teams_t_select")
    if t:
        # ---- Add team ----
        with st.form("add_team_form"):
            st.markdown("**Adicionar equipa**")
            c1, c2, c3 = st.columns([2, 2, 1])
            with c1:
                team_name_in = st.text_input("Nome da equipa *")
            with c2:
                logo_in = st.text_input("Logo URL (opcional)")
            with c3:
                seed_in = st.number_input("Seed (opcional)", 0, 256, 0, step=1)
            add_team = st.form_submit_button("Adicionar equipa")

        if add_team:
            if not team_name_in.strip():
                st.error("Nome da equipa é obrigatório.")
            else:
                try:
                    sb.table("tournament_teams").insert({
                        "tournament_id": t["id"],
                        "name": team_name_in.strip(),
                        "logo_url": logo_in.strip() or None,
                        "seed": int(seed_in) or None,
                        "admin_created_by": st.session_state.get("username"),
                    }).execute()
                    st.success("Equipa adicionada ✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao adicionar equipa: {e}")

        st.divider()
        teams = fetch_teams(t["id"])
        if not teams:
            st.info("Ainda não há equipas neste torneio.")
        else:
            profiles = fetch_profiles(sb)
            profile_opts = ["— Convidado (sem conta) —"] + [profile_label(p) for p in profiles]
            plabel_to_id = {profile_label(p): p["id"] for p in profiles}

            for team in teams:
                with st.expander(f"🛡️ {team_label(team)}", expanded=False):
                    members = (
                        sb.table("tournament_team_members")
                        .select("*")
                        .eq("team_id", team["id"])
                        .order("created_at")
                        .execute()
                        .data
                        or []
                    )
                    # name lookup for profile members
                    pid_to_name = {p["id"]: p.get("display_name") for p in profiles}
                    if members:
                        for m in members:
                            who = pid_to_name.get(m.get("profile_id")) or m.get("player_name") or "—"
                            tags = []
                            if m.get("is_captain"):
                                tags.append("©️ Capitão")
                            if m.get("jersey_number") is not None:
                                tags.append(f"#{m['jersey_number']}")
                            if not m.get("profile_id"):
                                tags.append("convidado")
                            meta = f"  ·  {' · '.join(tags)}" if tags else ""
                            mc1, mc2 = st.columns([5, 1])
                            mc1.write(f"- **{who}**{meta}")
                            if mc2.button("Remover", key=f"rm_{m['id']}"):
                                sb.table("tournament_team_members").delete().eq("id", m["id"]).execute()
                                st.rerun()
                    else:
                        st.caption("Sem jogadores.")

                    with st.form(f"add_member_{team['id']}"):
                        st.markdown("**Adicionar jogador**")
                        ac1, ac2, ac3 = st.columns([3, 1, 1])
                        with ac1:
                            prof_sel = st.selectbox(
                                "Jogador (conta) ou convidado", profile_opts,
                                key=f"prof_{team['id']}"
                            )
                            guest_name = st.text_input(
                                "Nome do convidado (se sem conta)", key=f"guest_{team['id']}"
                            )
                        with ac2:
                            jersey = st.number_input("Nº", 0, 99, 0, step=1, key=f"jersey_{team['id']}")
                        with ac3:
                            captain = st.checkbox("Capitão", key=f"cap_{team['id']}")
                        add_member = st.form_submit_button("Adicionar jogador")

                    if add_member:
                        profile_id = plabel_to_id.get(prof_sel)  # None if guest option
                        payload = {
                            "team_id": team["id"],
                            "profile_id": profile_id,
                            "player_name": guest_name.strip() or None if not profile_id else None,
                            "jersey_number": int(jersey) or None,
                            "is_captain": captain,
                        }
                        if not profile_id and not payload["player_name"]:
                            st.error("Escolhe um jogador com conta ou indica o nome do convidado.")
                        else:
                            try:
                                sb.table("tournament_team_members").insert(payload).execute()
                                st.success("Jogador adicionado ✅")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao adicionar jogador: {e}")

                    st.divider()
                    if st.button("🗑️ Eliminar equipa", key=f"del_team_{team['id']}"):
                        sb.table("tournament_teams").delete().eq("id", team["id"]).execute()
                        st.rerun()

# =======================================================================
# TAB 3: Groups & draw
# =======================================================================
with tab_g:
    st.subheader("Grupos & Sorteio")
    t = tournament_selectbox("groups_t_select")
    if t:
        if t.get("format") != "group_then_knockout":
            st.info(
                "Este torneio é de **eliminatória direta** — não tem fase de grupos. "
                "Muda o formato no separador *Torneios* se quiseres usar grupos."
            )
        else:
            # Create group
            with st.form("add_group_form"):
                gname = st.text_input("Nome do grupo (ex.: Grupo A) *")
                add_group = st.form_submit_button("Criar grupo")
            if add_group:
                if not gname.strip():
                    st.error("Nome do grupo é obrigatório.")
                else:
                    try:
                        sb.table("tournament_groups").insert({
                            "tournament_id": t["id"],
                            "name": gname.strip(),
                        }).execute()
                        st.success("Grupo criado ✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao criar grupo: {e}")

            st.divider()
            groups = fetch_groups(t["id"])
            teams = fetch_teams(t["id"])
            if not groups:
                st.info("Ainda não há grupos.")
            elif not teams:
                st.info("Cria equipas primeiro no separador *Equipas*.")
            else:
                gid_to_name = {g["id"]: g["name"] for g in groups}
                group_opts = ["— Sem grupo —"] + [g["name"] for g in groups]
                gname_to_id = {g["name"]: g["id"] for g in groups}

                st.markdown("**Atribuir equipas a grupos**")
                for team in teams:
                    cur = gid_to_name.get(team.get("group_id"), "— Sem grupo —")
                    sel = st.selectbox(
                        team["name"], group_opts,
                        index=group_opts.index(cur),
                        key=f"grp_{team['id']}",
                    )
                    new_gid = gname_to_id.get(sel)
                    if new_gid != team.get("group_id"):
                        sb.table("tournament_teams").update(
                            {"group_id": new_gid}
                        ).eq("id", team["id"]).execute()
                        st.rerun()

                st.divider()
                st.markdown("**Gerar jogos da fase de grupos** (todos-contra-todos por grupo)")
                if st.button("⚙️ Gerar jogos de grupo"):
                    created = 0
                    for g in groups:
                        gteams = [t2 for t2 in teams if t2.get("group_id") == g["id"]]
                        for i in range(len(gteams)):
                            for j in range(i + 1, len(gteams)):
                                sb.table("tournament_matches").insert({
                                    "tournament_id": t["id"],
                                    "stage": "group",
                                    "group_id": g["id"],
                                    "team_a_id": gteams[i]["id"],
                                    "team_b_id": gteams[j]["id"],
                                    "court_id": t.get("court_id"),
                                    "status": "scheduled",
                                    "admin_created_by": st.session_state.get("username"),
                                }).execute()
                                created += 1
                    st.success(f"{created} jogo(s) de grupo criado(s) ✅")

# =======================================================================
# TAB 4: Matches (scores, standings, bracket)
# =======================================================================
with tab_j:
    st.subheader("Jogos")
    t = tournament_selectbox("matches_t_select")
    if t:
        teams = fetch_teams(t["id"])
        team_by_id = {tm["id"]: tm for tm in teams}

        def tname(tid):
            tm = team_by_id.get(tid)
            return tm["name"] if tm else "— TBD —"

        # ---- Standings (group stage) ----
        if t.get("format") == "group_then_knockout":
            st.markdown("### 📊 Classificações de grupo")
            standings = (
                sb.table("tournament_group_standings")
                .select("*")
                .eq("tournament_id", t["id"])
                .order("group_id")
                .order("standing_points", desc=True)
                .order("point_diff", desc=True)
                .execute()
                .data
                or []
            )
            groups = fetch_groups(t["id"])
            gid_to_name = {g["id"]: g["name"] for g in groups}
            if standings:
                by_group = {}
                for row in standings:
                    by_group.setdefault(row["group_id"], []).append(row)
                for gid, rows in by_group.items():
                    st.markdown(f"**{gid_to_name.get(gid, 'Grupo')}**")
                    st.dataframe(
                        [
                            {
                                "Equipa": r["team_name"],
                                "J": r["played"],
                                "V": r["wins"],
                                "E": r["draws"],
                                "D": r["losses"],
                                "PM": r["points_for"],
                                "PS": r["points_against"],
                                "Dif": r["point_diff"],
                                "Pts": r["standing_points"],
                            }
                            for r in rows
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )
            else:
                st.caption("Sem jogos de grupo concluídos ainda.")
            st.divider()

        # ---- Generate knockout bracket ----
        st.markdown("### 🏟️ Gerar quadro de eliminatórias")
        st.caption(
            "Seleciona as equipas (pela ordem de seeding desejada). "
            "Equipas a mais para uma potência de 2 recebem 'bye' automático."
        )
        with st.form("gen_bracket_form"):
            team_opts = [team_label(tm) for tm in teams]
            tlabel_to_id = {team_label(tm): tm["id"] for tm in teams}
            chosen = st.multiselect("Equipas no quadro", team_opts)
            gen = st.form_submit_button("⚙️ Gerar quadro")

        if gen:
            ids = [tlabel_to_id[c] for c in chosen]
            if len(ids) < 2:
                st.error("Escolhe pelo menos 2 equipas.")
            else:
                try:
                    n_created = generate_bracket(sb, t, ids)
                    st.success(f"Quadro gerado com {n_created} jogo(s) ✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao gerar quadro: {e}")

        st.divider()

        # ---- Add single match manually ----
        with st.expander("➕ Adicionar jogo manualmente"):
            with st.form("add_match_form"):
                stage = st.selectbox("Fase", ["group", "knockout"])
                groups = fetch_groups(t["id"])
                group_id = None
                if stage == "group" and groups:
                    gsel = st.selectbox("Grupo", [g["name"] for g in groups])
                    group_id = next(g["id"] for g in groups if g["name"] == gsel)
                team_opts2 = ["— TBD —"] + [team_label(tm) for tm in teams]
                tlabel_to_id2 = {team_label(tm): tm["id"] for tm in teams}
                ca, cb = st.columns(2)
                with ca:
                    a_sel = st.selectbox("Equipa A", team_opts2, key="man_a")
                with cb:
                    b_sel = st.selectbox("Equipa B", team_opts2, key="man_b")
                rlabel = st.text_input("Etiqueta da ronda (ex.: Final)")
                add_match = st.form_submit_button("Adicionar jogo")
            if add_match:
                try:
                    sb.table("tournament_matches").insert({
                        "tournament_id": t["id"],
                        "stage": stage,
                        "group_id": group_id,
                        "team_a_id": tlabel_to_id2.get(a_sel),
                        "team_b_id": tlabel_to_id2.get(b_sel),
                        "round_label": rlabel.strip() or None,
                        "court_id": t.get("court_id"),
                        "status": "scheduled",
                        "admin_created_by": st.session_state.get("username"),
                    }).execute()
                    st.success("Jogo adicionado ✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao adicionar jogo: {e}")

        # ---- List matches + score entry ----
        st.markdown("### Resultados")
        matches = fetch_matches(t["id"])
        if not matches:
            st.info("Ainda não há jogos.")
        for m in matches:
            stage_txt = "Grupo" if m["stage"] == "group" else (m.get("round_label") or "Eliminatória")
            with st.container(border=True):
                st.markdown(
                    f"**{stage_txt}** — {tname(m.get('team_a_id'))} 🆚 {tname(m.get('team_b_id'))}  ·  `{m['status']}`"
                )
                with st.form(f"score_{m['id']}"):
                    sc1, sc2, sc3 = st.columns([1, 1, 2])
                    with sc1:
                        sa = st.number_input(
                            f"{tname(m.get('team_a_id'))}", 0, 500,
                            int(m["score_a"]) if m.get("score_a") is not None else 0,
                            step=1, key=f"sa_{m['id']}"
                        )
                    with sc2:
                        sb_score = st.number_input(
                            f"{tname(m.get('team_b_id'))}", 0, 500,
                            int(m["score_b"]) if m.get("score_b") is not None else 0,
                            step=1, key=f"sb_{m['id']}"
                        )
                    with sc3:
                        mstatus = st.selectbox(
                            "Estado", MATCH_STATUSES,
                            index=MATCH_STATUSES.index(m["status"]),
                            key=f"ms_{m['id']}"
                        )
                    save = st.form_submit_button("Guardar resultado")
                if save:
                    winner = None
                    if mstatus == "completed":
                        if sa > sb_score:
                            winner = m.get("team_a_id")
                        elif sb_score > sa:
                            winner = m.get("team_b_id")
                    try:
                        sb.table("tournament_matches").update({
                            "score_a": int(sa),
                            "score_b": int(sb_score),
                            "status": mstatus,
                            "winner_team_id": winner,
                        }).eq("id", m["id"]).execute()

                        # advance winner in the knockout bracket
                        if winner and m.get("next_match_id"):
                            advance_winner(sb, m, winner)
                        st.success("Resultado guardado ✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao guardar: {e}")
