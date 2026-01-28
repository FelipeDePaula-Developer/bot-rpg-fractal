import os
import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple

import discord

# ============================================================
# Config (catálogo e regras)
# ============================================================

DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "personagens.json")

MASTER_ROLE_NAME = "Mestre"

DEFAULT_DESTINY_MAX = 2

# Custo de XP para adicionar 1 fato novo (ajuste se quiser)
XP_COST_NEW_FACT = 3

# Limites "base" do sistema (ficha inicial)
BASE_FACT_LIMITS = {"past": 3, "present": 3, "future": 1}

# Catálogo (edite para bater com o PDF)
RACES: List[Tuple[str, str]] = [
    ("Humano", "Versátil e adaptável."),
    ("Anão", "Resiliente, tradição e forja."),
    ("Elfo", "Longevidade, precisão e magia."),
    ("Halfling", "Sortudo, discreto e ágil."),
]

CLASSES: List[Tuple[str, str]] = [
    ("Guerreiro", "Combate direto e resistência."),
    ("Ladino", "Furtividade, perícia, truques."),
    ("Clérigo", "Fé, cura e suporte."),
    ("Mago", "Magias e conhecimento arcano."),
]

ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "linha_de_frente": {"label": "Linha de frente", "pv": 8, "pm": 3, "dano_fisico_base": 2, "bonus_magico": 0},
    "combatente": {"label": "Combatente", "pv": 7, "pm": 3, "dano_fisico_base": 3, "bonus_magico": 0},
    "especialista": {"label": "Especialista", "pv": 6, "pm": 4, "dano_fisico_base": 2, "bonus_magico": 0},
    "utilitario": {"label": "Utilitário", "pv": 5, "pm": 4, "dano_fisico_base": 2, "bonus_magico": 0},
    "conjurador": {"label": "Conjurador", "pv": 4, "pm": 5, "dano_fisico_base": 1, "bonus_magico": 1},
}
ARCHETYPE_ORDER = ["linha_de_frente", "combatente", "especialista", "utilitario", "conjurador"]

# ============================================================
# Estado / storage
# ============================================================

data_lock = asyncio.Lock()
active_sessions: Dict[int, bool] = {}  # user_id -> bool


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


async def load_data() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        return {}
    async with data_lock:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)


async def save_data(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    async with data_lock:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)


def is_master(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.name == MASTER_ROLE_NAME for r in member.roles)


# ============================================================
# Schema NOVO (somente)
# ============================================================

def make_new_character_schema(user_id: int) -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "owner_id": user_id,
        "name": "",
        "race": "",
        "class": "",
        "archetype": "",
        "reserves": {
            "pv": {"current": 0, "max": 0},
            "pm": {"current": 0, "max": 0},
            "destiny": {"current": DEFAULT_DESTINY_MAX, "max": DEFAULT_DESTINY_MAX},
        },
        "damage_base": {"physical": 0, "magic_bonus": 0},
        "facts": {"past": [], "present": [], "future": []},  # base 3/3/1
        "difficulty": "",  # 1
        "ruptured_facts": [],  # lista de textos de fatos rompidos
        "xp": 0,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }


def apply_archetype(character: Dict[str, Any], archetype_key: str) -> None:
    arch = ARCHETYPES[archetype_key]
    character["archetype"] = archetype_key
    character["reserves"]["pv"] = {"current": arch["pv"], "max": arch["pv"]}
    character["reserves"]["pm"] = {"current": arch["pm"], "max": arch["pm"]}
    character["reserves"]["destiny"] = {"current": DEFAULT_DESTINY_MAX, "max": DEFAULT_DESTINY_MAX}
    character["damage_base"] = {"physical": arch["dano_fisico_base"], "magic_bonus": arch["bonus_magico"]}


def render_character(character: Dict[str, Any]) -> str:
    arch_key = character.get("archetype") or ""
    arch_label = ARCHETYPES.get(arch_key, {}).get("label", "—") if arch_key else "—"

    pv = character["reserves"]["pv"]
    pm = character["reserves"]["pm"]
    destiny = character["reserves"]["destiny"]
    dmg = character.get("damage_base", {"physical": 0, "magic_bonus": 0})

    past = character["facts"]["past"]
    present = character["facts"]["present"]
    future = character["facts"]["future"]

    rupt = character.get("ruptured_facts", [])

    def fmt(items):
        if not items:
            return "—"
        return "\n".join(f"- {x}" for x in items)

    def fmt_rupt(items):
        if not items:
            return "—"
        return "\n".join(f"- ~~{x}~~" for x in items)

    return (
        f"**Nome:** {character.get('name','—')}\n"
        f"**Raça:** {character.get('race','—')}\n"
        f"**Classe:** {character.get('class','—')}\n"
        f"**Arquétipo:** {arch_label}\n"
        f"**Reservas:** PV {pv['current']}/{pv['max']} | PM {pm['current']}/{pm['max']} | "
        f"Destino {destiny['current']}/{destiny['max']}\n"
        f"**Dano Base:** Físico {dmg.get('physical',0)} | Bônus mágico +{dmg.get('magic_bonus',0)}\n"
        f"**XP:** {character.get('xp',0)}\n\n"
        f"**Fatos — Passado** (base {BASE_FACT_LIMITS['past']})\n{fmt(past)}\n\n"
        f"**Fatos — Presente** (base {BASE_FACT_LIMITS['present']})\n{fmt(present)}\n\n"
        f"**Fatos — Futuro** (base {BASE_FACT_LIMITS['future']})\n{fmt(future)}\n\n"
        f"**Dificuldade (1)**\n- {character.get('difficulty') or '—'}\n\n"
        f"**Fatos Rompidos**\n{fmt_rupt(rupt)}"
    )


# ============================================================
# DM helpers (texto + select)
# ============================================================

async def dm_ask_text(client: discord.Client, user: discord.User, prompt: str, *, timeout: int = 180) -> Optional[str]:
    dm = user.dm_channel or await user.create_dm()
    await dm.send(prompt)

    def check(msg: discord.Message):
        return msg.author.id == user.id and msg.channel.id == dm.id

    try:
        msg = await client.wait_for("message", check=check, timeout=timeout)
        return (msg.content or "").strip()
    except asyncio.TimeoutError:
        return None


@dataclass
class _SessionState:
    user: discord.User
    done: asyncio.Event


class _SingleSelect(discord.ui.Select):
    def __init__(self, *, placeholder: str, options: List[discord.SelectOption]):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)


class _SelectView(discord.ui.View):
    def __init__(self, *, state: _SessionState, select: _SingleSelect, timeout: int = 180):
        super().__init__(timeout=timeout)
        self.state = state
        self.select = select
        self.add_item(select)

    async def on_timeout(self) -> None:
        if not self.state.done.is_set():
            self.state.done.set()


async def dm_select_one(
    user: discord.User,
    *,
    title: str,
    placeholder: str,
    option_tuples: List[Tuple[str, str]],
    timeout: int = 180,
) -> Optional[str]:
    """
    option_tuples: [(label, description)] -> retorna label escolhido
    """
    dm = user.dm_channel or await user.create_dm()
    done = asyncio.Event()
    state = _SessionState(user=user, done=done)

    options: List[discord.SelectOption] = []
    for label, desc in option_tuples[:25]:
        options.append(
            discord.SelectOption(
                label=label,
                description=(desc[:100] if desc else None),
                value=label
            )
        )

    select = _SingleSelect(placeholder=placeholder, options=options)

    async def callback(interaction: discord.Interaction):
        if interaction.user.id != user.id:
            await interaction.response.send_message("Esse menu não é seu.", ephemeral=True)
            return
        done.value = select.values[0]  # type: ignore[attr-defined]
        await interaction.response.edit_message(content=f"✅ Selecionado: **{select.values[0]}**", view=None)
        done.set()

    select.callback = callback  # type: ignore[assignment]

    view = _SelectView(state=state, select=select, timeout=timeout)
    await dm.send(f"**{title}**", view=view)

    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass

    return getattr(done, "value", None)


async def dm_select_archetype(user: discord.User, *, timeout: int = 180) -> Optional[str]:
    dm = user.dm_channel or await user.create_dm()
    done = asyncio.Event()
    state = _SessionState(user=user, done=done)

    options: List[discord.SelectOption] = []
    for key in ARCHETYPE_ORDER:
        a = ARCHETYPES[key]
        label = a["label"]
        desc = (
            f"PV {a['pv']} / PM {a['pm']} / Dano {a['dano_fisico_base']}"
            + (f" / Magia +{a['bonus_magico']}" if a["bonus_magico"] else "")
        )
        options.append(discord.SelectOption(label=label, description=desc[:100], value=key))

    select = _SingleSelect(placeholder="Escolha seu Arquétipo", options=options)

    async def callback(interaction: discord.Interaction):
        if interaction.user.id != user.id:
            await interaction.response.send_message("Esse menu não é seu.", ephemeral=True)
            return
        done.value = select.values[0]  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            content=f"✅ Arquétipo: **{ARCHETYPES[select.values[0]]['label']}**",
            view=None,
        )
        done.set()

    select.callback = callback  # type: ignore[assignment]
    view = _SelectView(state=state, select=select, timeout=timeout)
    await dm.send("**Selecione seu Arquétipo**", view=view)

    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass

    return getattr(done, "value", None)


# ============================================================
# Fatos (helpers)
# ============================================================

def _all_facts_with_index(char: Dict[str, Any]) -> List[Tuple[str, str, int]]:
    """
    Retorna lista de (kind, fact_text, global_index)
    kind: 'past'|'present'|'future'
    """
    out = []
    idx = 0
    for kind in ("past", "present", "future"):
        for f in char["facts"][kind]:
            out.append((kind, f, idx))
            idx += 1
    return out


def _options_all_facts(char: Dict[str, Any]) -> List[Tuple[str, str]]:
    opts = []
    for kind, f, idx in _all_facts_with_index(char):
        kind_label = {"past": "Passado", "present": "Presente", "future": "Futuro"}[kind]
        short = f if len(f) <= 80 else f[:77] + "..."
        opts.append((f"{kind_label}: {short}", str(idx)))
    return opts


def _options_non_ruptured_facts(char: Dict[str, Any]) -> List[Tuple[str, str]]:
    rupt = set(char.get("ruptured_facts", []))
    opts = []
    for kind, f, idx in _all_facts_with_index(char):
        if f in rupt:
            continue
        kind_label = {"past": "Passado", "present": "Presente", "future": "Futuro"}[kind]
        short = f if len(f) <= 80 else f[:77] + "..."
        opts.append((f"{kind_label}: {short}", str(idx)))
    return opts


def _set_fact_by_global_index(char: Dict[str, Any], global_index: int, new_text: str) -> Optional[str]:
    """
    Edita um fato pelo índice global (past+present+future).
    Retorna texto antigo ou None se inválido.
    """
    idx = 0
    for kind in ("past", "present", "future"):
        arr = char["facts"][kind]
        if global_index < idx + len(arr):
            local = global_index - idx
            old = arr[local]
            arr[local] = new_text
            char["facts"][kind] = arr
            return old
        idx += len(arr)
    return None


# ============================================================
# Wizard (criação)
# ============================================================

async def run_character_wizard(client: discord.Client, user: discord.User) -> Optional[Dict[str, Any]]:
    if active_sessions.get(user.id):
        return None
    active_sessions[user.id] = True

    try:
        char = make_new_character_schema(user.id)

        # Nome
        name = await dm_ask_text(client, user, "📜 Vamos criar sua ficha (regras novas).\n\n**Qual o nome do personagem?**")
        if not name:
            return None
        char["name"] = name

        # Raça
        race = await dm_select_one(
            user,
            title="Selecione sua Raça",
            placeholder="Escolha a raça",
            option_tuples=RACES,
        )
        if not race:
            return None
        char["race"] = race

        # Classe
        clazz = await dm_select_one(
            user,
            title="Selecione sua Classe",
            placeholder="Escolha a classe",
            option_tuples=CLASSES,
        )
        if not clazz:
            return None
        char["class"] = clazz

        # Arquétipo
        archetype_key = await dm_select_archetype(user)
        if not archetype_key:
            return None
        apply_archetype(char, archetype_key)

        # Fatos e Dificuldade
        dm = user.dm_channel or await user.create_dm()
        await dm.send(
            "🧩 Agora vamos definir seus **7 Fatos**: **3 Passado**, **3 Presente**, **1 Futuro**.\n"
            "Escreva frases curtas e jogáveis."
        )

        for i in range(1, 4):
            txt = await dm_ask_text(client, user, f"**Passado {i}/3** — Escreva um fato do seu passado:")
            if not txt:
                return None
            char["facts"]["past"].append(txt)

        for i in range(1, 4):
            txt = await dm_ask_text(client, user, f"**Presente {i}/3** — Escreva um fato do seu presente:")
            if not txt:
                return None
            char["facts"]["present"].append(txt)

        txt = await dm_ask_text(client, user, "**Futuro 1/1** — Escreva um fato do seu futuro (presságio/destino/promessa):")
        if not txt:
            return None
        char["facts"]["future"].append(txt)

        diff = await dm_ask_text(client, user, "⚠️ **Dificuldade (1)** — Qual é a sua dificuldade (fraqueza/problema/risco)?")
        if not diff:
            return None
        char["difficulty"] = diff

        char["updated_at"] = utc_now_iso()

        await dm.send("✅ **Ficha criada!**\n\n" + render_character(char))
        return char

    finally:
        active_sessions.pop(user.id, None)


# ============================================================
# Operações de ficha (comandos)
# ============================================================

async def get_character(owner_id: int) -> Optional[Dict[str, Any]]:
    data = await load_data()
    return data.get(str(owner_id))


async def save_character(owner_id: int, char: Dict[str, Any]) -> None:
    data = await load_data()
    data[str(owner_id)] = char
    await save_data(data)


async def set_reserve(owner_id: int, reserve_key: str, new_current_value: int) -> Tuple[bool, str]:
    reserve_key = (reserve_key or "").strip().lower()
    if reserve_key not in ("pv", "pm", "destiny"):
        return False, "Tipo inválido. Use: pv, pm ou destiny."

    data = await load_data()
    char = data.get(str(owner_id))
    if not char:
        return False, "Você não tem ficha. Use `/criar_personagem`."

    res = char["reserves"][reserve_key]
    vmax = int(res["max"])
    vcur = max(0, min(vmax, int(new_current_value)))
    res["current"] = vcur
    char["updated_at"] = utc_now_iso()

    data[str(owner_id)] = char
    await save_data(data)

    return True, f"{reserve_key.upper()} agora está em {vcur}/{vmax}."


async def rest_character(owner_id: int) -> Tuple[bool, str]:
    data = await load_data()
    char = data.get(str(owner_id))
    if not char:
        return False, "Você não tem ficha. Use `/criar_personagem`."

    # Descansar: volta tudo ao máximo (PV/PM/Destino)
    for k in ("pv", "pm", "destiny"):
        char["reserves"][k]["current"] = int(char["reserves"][k]["max"])

    char["updated_at"] = utc_now_iso()
    data[str(owner_id)] = char
    await save_data(data)

    return True, "Você descansou. PV/PM/Destino foram restaurados ao máximo."


async def add_fact_with_xp(client: discord.Client, user: discord.User) -> Tuple[bool, str]:
    data = await load_data()
    char = data.get(str(user.id))
    if not char:
        return False, "Você não tem ficha. Use `/criar_personagem`."

    xp = int(char.get("xp", 0))
    if xp < XP_COST_NEW_FACT:
        return False, f"XP insuficiente. Você tem {xp} XP e precisa de {XP_COST_NEW_FACT} XP."

    # Escolher categoria
    kind = await dm_select_one(
        user,
        title="Adicionar novo Fato",
        placeholder="Escolha onde entra o fato",
        option_tuples=[
            ("Passado", "Um evento/verdade do passado."),
            ("Presente", "Algo verdadeiro agora."),
            ("Futuro", "Presságio/promessa/destino."),
        ],
    )
    if not kind:
        return False, "Ação cancelada/expirada."

    kind_key = {"Passado": "past", "Presente": "present", "Futuro": "future"}[kind]
    txt = await dm_ask_text(client, user, f"Escreva o **novo fato** ({kind}):")
    if not txt:
        return False, "Ação cancelada/expirada."

    # Debita XP e adiciona
    char["xp"] = xp - XP_COST_NEW_FACT
    char["facts"][kind_key].append(txt)
    char["updated_at"] = utc_now_iso()

    data[str(user.id)] = char
    await save_data(data)

    return True, f"Fato adicionado em **{kind}** e {XP_COST_NEW_FACT} XP foram gastos. (XP atual: {char['xp']})"


async def edit_fact_flow(client: discord.Client, user: discord.User) -> Tuple[bool, str]:
    data = await load_data()
    char = data.get(str(user.id))
    if not char:
        return False, "Você não tem ficha. Use `/criar_personagem`."

    options = _options_all_facts(char)
    if not options:
        return False, "Você não tem fatos para editar."

    chosen = await dm_select_one(
        user,
        title="Editar Fato",
        placeholder="Escolha o fato para editar",
        option_tuples=options,
    )
    if not chosen:
        return False, "Ação cancelada/expirada."

    idx = int(chosen)
    old = _all_facts_with_index(char)[idx][1]  # texto antigo
    txt = await dm_ask_text(client, user, "Digite o **novo texto** para esse fato:\n\n" + f"Atual: `{old}`")
    if not txt:
        return False, "Ação cancelada/expirada."

    old_text = _set_fact_by_global_index(char, idx, txt)
    if old_text is None:
        return False, "Índice inválido (erro interno)."

    # Se o fato antigo estava na lista de rompidos, atualiza também (remove antigo e adiciona novo se quiser manter rompido)
    rupt = char.get("ruptured_facts", [])
    if old_text in rupt:
        rupt = [x for x in rupt if x != old_text]
        rupt.append(txt)
        char["ruptured_facts"] = rupt

    char["updated_at"] = utc_now_iso()
    data[str(user.id)] = char
    await save_data(data)

    return True, "Fato atualizado com sucesso."


async def rupture_fact_flow(user: discord.User) -> Tuple[bool, str]:
    data = await load_data()
    char = data.get(str(user.id))
    if not char:
        return False, "Você não tem ficha. Use `/criar_personagem`."

    options = _options_non_ruptured_facts(char)
    if not options:
        return False, "Não há fatos disponíveis para ruptura (todos já rompidos ou inexistentes)."

    chosen = await dm_select_one(
        user,
        title="Ruptura de Fato",
        placeholder="Escolha um fato para romper",
        option_tuples=options,
    )
    if not chosen:
        return False, "Ação cancelada/expirada."

    idx = int(chosen)
    fact_text = _all_facts_with_index(char)[idx][1]

    # Marca rompido + ganha 1 XP + restaura PV/PM (e opcionalmente destino)
    rupt = char.get("ruptured_facts", [])
    if fact_text not in rupt:
        rupt.append(fact_text)
    char["ruptured_facts"] = rupt

    char["xp"] = int(char.get("xp", 0)) + 1

    # efeito “seguro”: recupera PV/PM ao máximo
    char["reserves"]["pv"]["current"] = int(char["reserves"]["pv"]["max"])
    char["reserves"]["pm"]["current"] = int(char["reserves"]["pm"]["max"])

    char["updated_at"] = utc_now_iso()
    data[str(user.id)] = char
    await save_data(data)

    return True, "Ruptura realizada: fato marcado como rompido, +1 XP e PV/PM restaurados."


async def get_condition_text(owner_id: int) -> Tuple[bool, str]:
    data = await load_data()
    char = data.get(str(owner_id))
    if not char:
        return False, "Você não tem ficha. Use `/criar_personagem`."
    pv = char["reserves"]["pv"]
    pm = char["reserves"]["pm"]
    ds = char["reserves"]["destiny"]
    return True, f"Condição/Reservas: PV {pv['current']}/{pv['max']} | PM {pm['current']}/{pm['max']} | Destino {ds['current']}/{ds['max']}."


async def xp_adjust(owner_id: int, delta: int) -> Tuple[bool, str]:
    data = await load_data()
    char = data.get(str(owner_id))
    if not char:
        return False, "Ficha não encontrada."
    char["xp"] = max(0, int(char.get("xp", 0)) + int(delta))
    char["updated_at"] = utc_now_iso()
    data[str(owner_id)] = char
    await save_data(data)
    return True, f"XP agora: {char['xp']}."
