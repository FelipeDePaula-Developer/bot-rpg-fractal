import os
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any

import discord
from discord import app_commands

# ---------------- Config ----------------

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "personagens.json")

MASTER_ROLE_NAME = "Mestre"
DEFAULT_CONDITION_MAX = 3
XP_COST_NEW_FACT = 3

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.dm_messages = True
intents.messages = True
intents.message_content = True  # usado no wizard por DM

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

data_lock = asyncio.Lock()
active_sessions: Dict[int, bool] = {}

# ---------------- Storage ----------------

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

# ---------------- Permissions ----------------

def is_master(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.name == MASTER_ROLE_NAME for r in member.roles)

def can_target(interaction: discord.Interaction, usuario: Optional[discord.Member]) -> bool:
    # se não tem alvo explícito, sempre ok (é o próprio)
    if usuario is None:
        return True
    # se tem alvo explícito, precisa ser mestre/admin
    return is_master(interaction.user)  # type: ignore[arg-type]

# ---------------- Character Helpers ----------------

def ensure_char_defaults(char: dict) -> dict:
    char.setdefault("facts", {})
    char["facts"].setdefault("past", [])
    char["facts"].setdefault("present", [])
    char["facts"].setdefault("future", [])
    char.setdefault("ruptured_facts", [])
    char.setdefault("condition", {"current": DEFAULT_CONDITION_MAX, "max": DEFAULT_CONDITION_MAX})
    char.setdefault("xp", 0)
    return char

def flatten_facts(char: dict) -> List[str]:
    facts = char.get("facts", {})
    return (facts.get("past", []) or []) + (facts.get("present", []) or []) + (facts.get("future", []) or [])

def set_fact_by_index(char: dict, index: int, new_text: str) -> Optional[str]:
    """Edita um fato pelo índice global (past+present+future). Retorna o texto antigo."""
    facts = char.get("facts", {})
    past = facts.get("past", []) or []
    present = facts.get("present", []) or []
    future = facts.get("future", []) or []

    total = len(past) + len(present) + len(future)
    if index < 0 or index >= total:
        return None

    if index < len(past):
        old = past[index]
        past[index] = new_text
        facts["past"] = past
        return old

    index -= len(past)
    if index < len(present):
        old = present[index]
        present[index] = new_text
        facts["present"] = present
        return old

    index -= len(present)
    old = future[index]
    future[index] = new_text
    facts["future"] = future
    return old

def list_fact_options_not_ruptured(char: dict) -> List[Tuple[str, str]]:
    """Lista fatos ainda não rompidos (máx 25 por limitação do select)."""
    ruptured = set(char.get("ruptured_facts", []))
    facts = char.get("facts", {})

    options: List[Tuple[str, str]] = []
    idx = 0

    def scan(kind: str, arr: list):
        nonlocal idx, options
        for fact in (arr or []):
            current_index = idx
            idx += 1
            if not fact:
                continue
            if fact in ruptured:
                continue
            short = fact if len(fact) <= 80 else fact[:77] + "..."
            options.append((f"{kind}: {short}", str(current_index)))

    scan("Passado", facts.get("past", []))
    scan("Presente", facts.get("present", []))
    scan("Futuro", facts.get("future", []))
    return options

def list_all_fact_options(char: dict) -> List[Tuple[str, str]]:
    """Lista todos os fatos para edição."""
    facts = char.get("facts", {})
    options: List[Tuple[str, str]] = []
    idx = 0

    def scan(kind: str, arr: list):
        nonlocal idx, options
        for fact in (arr or []):
            current_index = idx
            idx += 1
            if not fact:
                continue
            short = fact if len(fact) <= 80 else fact[:77] + "..."
            options.append((f"{kind}: {short}", str(current_index)))

    scan("Passado", facts.get("past", []))
    scan("Presente", facts.get("present", []))
    scan("Futuro", facts.get("future", []))
    return options

def render_character(char: dict) -> str:
    facts = char.get("facts", {})
    past = facts.get("past", [])
    present = facts.get("present", [])
    future = facts.get("future", [])
    ruptured_facts = char.get("ruptured_facts", [])

    cond = char.get("condition", {"current": 0, "max": 0})
    xp = char.get("xp", 0)

    def fmt_list(items):
        if not items:
            return "—"
        return "\n".join([f"- {x}" for x in items])

    return (
        f"**Nome:** {char.get('name','—')}\n"
        f"**Condição/Vida:** {cond.get('current',0)}/{cond.get('max',0)}\n"
        f"**XP:** {xp}\n\n"
        f"**Fatos — Passado**\n{fmt_list(past)}\n\n"
        f"**Fatos — Presente**\n{fmt_list(present)}\n\n"
        f"**Fatos — Futuro**\n{fmt_list(future)}\n\n"
        f"**Defeito:** {char.get('flaw','—')}\n"
        f"**Fatos Rompidos:**\n{fmt_list(ruptured_facts)}\n"
    )

async def get_char_or_reply(interaction: discord.Interaction, target: discord.Member) -> Optional[dict]:
    data = await load_data()
    uid = str(target.id)
    char = data.get(uid)
    if not char:
        await interaction.response.send_message("Esse usuário ainda não tem ficha criada.", ephemeral=True)
        return None
    return ensure_char_defaults(char)

async def save_char(target_id: str, char: dict) -> None:
    data = await load_data()
    data[target_id] = char
    await save_data(data)

# ---------------- Wizard DM ----------------

async def ask_dm(user: discord.User, question: str, timeout: int = 300) -> str:
    dm = user.dm_channel or await user.create_dm()
    await dm.send(question)

    def check(m: discord.Message):
        return (
            m.author.id == user.id
            and isinstance(m.channel, discord.DMChannel)
            and m.content is not None
            and m.content.strip() != ""
        )

    msg = await client.wait_for("message", check=check, timeout=timeout)
    return msg.content.strip()

# ---------------- UI: Ruptura ----------------

class RupturaSelect(discord.ui.Select):
    def __init__(self, *, requester_id: int, target_user_id: str, options_pairs: List[Tuple[str, str]]):
        self.requester_id = requester_id
        self.target_user_id = target_user_id

        discord_options = [
            discord.SelectOption(label=label, value=value)
            for label, value in options_pairs[:25]
        ]
        super().__init__(
            placeholder="Escolha o fato que vai romper (desabilitar)",
            min_values=1,
            max_values=1,
            options=discord_options
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Só quem executou o comando pode escolher aqui.", ephemeral=True)
            return

        chosen_index = int(self.values[0])

        data = await load_data()
        char = data.get(self.target_user_id)
        if not char:
            await interaction.response.send_message("Ficha não encontrada.", ephemeral=True)
            return

        char = ensure_char_defaults(char)
        fact = flatten_facts(char)
        if chosen_index < 0 or chosen_index >= len(fact):
            await interaction.response.send_message("Não encontrei esse fato. Rode o comando de novo.", ephemeral=True)
            return

        fact_text = fact[chosen_index]
        ruptured = char.get("ruptured_facts", [])
        if fact_text in ruptured:
            await interaction.response.send_message("Esse fato já está rompido.", ephemeral=True)
            return

        ruptured.append(fact_text)
        char["ruptured_facts"] = ruptured
        char["updated_at"] = utc_now_iso()
        data[self.target_user_id] = char
        await save_data(data)

        await interaction.response.send_message(f"💥 **Ruptura aplicada!**\nFato rompido: **{fact_text}**", ephemeral=True)

class RupturaView(discord.ui.View):
    def __init__(self, *, requester_id: int, target_user_id: str, options_pairs: List[Tuple[str, str]]):
        super().__init__(timeout=60)
        self.add_item(RupturaSelect(
            requester_id=requester_id,
            target_user_id=target_user_id,
            options_pairs=options_pairs
        ))

# ---------------- UI: Novo Fato (XP) ----------------

class NovoFatoModal(discord.ui.Modal, title="Adicionar novo Fato (custa 3 XP)"):
    fato = discord.ui.TextInput(
        label="Escreva o novo fato",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=True,
        placeholder="Ex: Eu já servi no exército do duque e tenho contatos na guarda."
    )

    def __init__(self, *, requester_id: int, target_user_id: str, timeline: str):
        super().__init__()
        self.requester_id = requester_id
        self.target_user_id = target_user_id
        self.timeline = timeline

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Só quem abriu o modal pode enviar.", ephemeral=True)
            return

        data = await load_data()
        char = data.get(self.target_user_id)
        if not char:
            await interaction.response.send_message("Ficha não encontrada.", ephemeral=True)
            return

        char = ensure_char_defaults(char)
        xp = int(char.get("xp", 0))
        if xp < XP_COST_NEW_FACT:
            await interaction.response.send_message("Você precisa de **3 XP** para criar um novo fato.", ephemeral=True)
            return

        new_fact = str(self.fato.value).strip()
        if not new_fact:
            await interaction.response.send_message("Fato vazio não pode.", ephemeral=True)
            return

        char["facts"][self.timeline].append(new_fact)
        char["xp"] = xp - XP_COST_NEW_FACT
        char["updated_at"] = utc_now_iso()

        data[self.target_user_id] = char
        await save_data(data)

        label = {"past": "Passado", "present": "Presente", "future": "Futuro"}.get(self.timeline, self.timeline)
        await interaction.response.send_message(
            f"✅ Novo fato adicionado em **{label}** e **3 XP** foram gastos.\n"
            f"XP atual: **{char['xp']}**\n\n"
            f"Fato: **{new_fact}**",
            ephemeral=True
        )

class TimelineSelect(discord.ui.Select):
    def __init__(self, *, requester_id: int, target_user_id: str):
        self.requester_id = requester_id
        self.target_user_id = target_user_id

        options = [
            discord.SelectOption(label="Passado", value="past"),
            discord.SelectOption(label="Presente", value="present"),
            discord.SelectOption(label="Futuro", value="future"),
        ]

        super().__init__(
            placeholder="Escolha onde adicionar o novo fato",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Só quem executou o comando pode escolher.", ephemeral=True)
            return

        timeline = self.values[0]
        await interaction.response.send_modal(
            NovoFatoModal(requester_id=self.requester_id, target_user_id=self.target_user_id, timeline=timeline)
        )

class TimelineView(discord.ui.View):
    def __init__(self, *, requester_id: int, target_user_id: str):
        super().__init__(timeout=60)
        self.add_item(TimelineSelect(requester_id=requester_id, target_user_id=target_user_id))

# ---------------- UI: Editar Fato ----------------

class EditarFatoModal(discord.ui.Modal, title="Editar Fato"):
    novo_texto = discord.ui.TextInput(
        label="Novo texto do fato",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=True
    )

    def __init__(self, *, requester_id: int, target_user_id: str, fact_index: int, current_text: str):
        super().__init__()
        self.requester_id = requester_id
        self.target_user_id = target_user_id
        self.fact_index = fact_index
        self.novo_texto.default = current_text

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Só quem iniciou pode enviar.", ephemeral=True)
            return

        new_text = str(self.novo_texto.value).strip()
        if not new_text:
            await interaction.response.send_message("O fato não pode ficar vazio.", ephemeral=True)
            return

        data = await load_data()
        char = data.get(self.target_user_id)
        if not char:
            await interaction.response.send_message("Ficha não encontrada.", ephemeral=True)
            return

        char = ensure_char_defaults(char)
        old_text = set_fact_by_index(char, self.fact_index, new_text)
        if old_text is None:
            await interaction.response.send_message("Não encontrei esse fato. Rode o comando de novo.", ephemeral=True)
            return

        # se estava rompido, troca também na lista de rompidos
        ruptured = char.get("ruptured_facts", [])
        if old_text in ruptured:
            char["ruptured_facts"] = [new_text if x == old_text else x for x in ruptured]

        char["updated_at"] = utc_now_iso()
        data[self.target_user_id] = char
        await save_data(data)

        await interaction.response.send_message(
            f"✅ Fato atualizado!\n\n**Antes:** {old_text}\n**Depois:** {new_text}",
            ephemeral=True
        )

class EditarFatoSelect(discord.ui.Select):
    def __init__(self, *, requester_id: int, target_user_id: str, options_pairs: List[Tuple[str, str]]):
        self.requester_id = requester_id
        self.target_user_id = target_user_id

        discord_options = [
            discord.SelectOption(label=label, value=value)
            for label, value in options_pairs[:25]
        ]

        super().__init__(
            placeholder="Escolha o fato que você quer editar",
            min_values=1,
            max_values=1,
            options=discord_options
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Só quem executou o comando pode escolher.", ephemeral=True)
            return

        fact_index = int(self.values[0])

        data = await load_data()
        char = data.get(self.target_user_id)
        if not char:
            await interaction.response.send_message("Ficha não encontrada.", ephemeral=True)
            return

        char = ensure_char_defaults(char)
        facts_flat = flatten_facts(char)
        if fact_index < 0 or fact_index >= len(facts_flat):
            await interaction.response.send_message("Não achei esse fato. Rode o comando de novo.", ephemeral=True)
            return

        await interaction.response.send_modal(
            EditarFatoModal(
                requester_id=self.requester_id,
                target_user_id=self.target_user_id,
                fact_index=fact_index,
                current_text=facts_flat[fact_index]
            )
        )

class EditarFatoView(discord.ui.View):
    def __init__(self, *, requester_id: int, target_user_id: str, options_pairs: List[Tuple[str, str]]):
        super().__init__(timeout=60)
        self.add_item(EditarFatoSelect(
            requester_id=requester_id,
            target_user_id=target_user_id,
            options_pairs=options_pairs
        ))

# ---------------- Commands ----------------

@tree.command(name="personagem_criar", description="Cria sua ficha (wizard por DM) e salva em JSON.")
async def personagem_criar(interaction: discord.Interaction):
    user = interaction.user

    if active_sessions.get(user.id):
        await interaction.response.send_message("Você já está com um wizard aberto. Responda no DM.", ephemeral=True)
        return

    active_sessions[user.id] = True
    await interaction.response.send_message("Beleza! Vou te mandar as perguntas no seu DM agora. ✅", ephemeral=True)

    try:
        name = await ask_dm(user, "🧾 **Ficha Fractal**\n\n1) **Nome?**")
        past1 = await ask_dm(user, "2) **Fato sobre o Passado (1/2)?**")
        past2 = await ask_dm(user, "3) **Fato sobre o Passado (2/2)?**")
        pres1 = await ask_dm(user, "4) **Fato sobre o Presente (1/2)?**")
        pres2 = await ask_dm(user, "5) **Fato sobre o Presente (2/2)?**")
        fut1 = await ask_dm(user, "6) **Fato sobre o Futuro (1/1)?**")
        flaw = await ask_dm(user, "7) Por fim: **Defeito?**")

        data = await load_data()
        uid = str(user.id)
        now = utc_now_iso()

        char = ensure_char_defaults({
            "user_id": uid,
            "name": name,
            "facts": {"past": [past1, past2], "present": [pres1, pres2], "future": [fut1]},
            "flaw": flaw,
            "condition": {"current": DEFAULT_CONDITION_MAX, "max": DEFAULT_CONDITION_MAX},
            "xp": 0,
            "ruptured_facts": [],
            "created_at": data.get(uid, {}).get("created_at", now),
            "updated_at": now,
        })

        data[uid] = char
        await save_data(data)

        dm = user.dm_channel or await user.create_dm()
        await dm.send("✅ **Ficha criada e salva!**\n\n" + render_character(char))

    except asyncio.TimeoutError:
        dm = user.dm_channel or await user.create_dm()
        await dm.send("⏱️ Tempo esgotado. Rode `/personagem_criar` de novo.")
    except discord.Forbidden:
        await interaction.followup.send("Não consegui te mandar DM. Libera DM do servidor e tenta de novo.", ephemeral=True)
    finally:
        active_sessions.pop(user.id, None)

@tree.command(name="personagem_ver", description="Mostra sua ficha (ou de outro se Mestre/Admin).")
@app_commands.describe(usuario="(opcional) usuário alvo; somente Mestre/Admin")
async def personagem_ver(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    if not interaction.guild:
        await interaction.response.send_message("Use esse comando dentro de um servidor.", ephemeral=True)
        return

    if usuario and not is_master(interaction.user):  # type: ignore[arg-type]
        await interaction.response.send_message("Você não tem permissão para consultar fichas.", ephemeral=True)
        return

    target = usuario or interaction.user  # type: ignore[assignment]
    data = await load_data()
    char = data.get(str(target.id))
    if not char:
        await interaction.response.send_message("Esse usuário ainda não tem ficha criada.", ephemeral=True)
        return

    await interaction.response.send_message(render_character(ensure_char_defaults(char)), ephemeral=True)

@tree.command(name="personagem_xp", description="Ajusta XP do seu personagem (ou de outro se Mestre/Admin).")
@app_commands.describe(delta="quanto somar/subtrair (ex: 1, -1)", usuario="(opcional) alvo; só Mestre/Admin")
async def personagem_xp(interaction: discord.Interaction, delta: int, usuario: Optional[discord.Member] = None):
    if not interaction.guild:
        await interaction.response.send_message("Use esse comando dentro de um servidor.", ephemeral=True)
        return

    if usuario and not is_master(interaction.user):  # type: ignore[arg-type]
        await interaction.response.send_message("Só Mestre/Admin pode alterar XP de outros.", ephemeral=True)
        return

    target = usuario or interaction.user  # type: ignore[assignment]
    data = await load_data()
    uid = str(target.id)
    char = data.get(uid)
    if not char:
        await interaction.response.send_message("Esse usuário ainda não tem ficha criada.", ephemeral=True)
        return

    char = ensure_char_defaults(char)
    char["xp"] = int(char.get("xp", 0)) + int(delta)
    char["updated_at"] = utc_now_iso()
    data[uid] = char
    await save_data(data)

    await interaction.response.send_message(f"✅ XP de **{target.display_name}** agora é **{char['xp']}**.", ephemeral=True)

@tree.command(name="personagem_condicao", description="Ajusta condição/vida (ou de outro se Mestre/Admin).")
@app_commands.describe(delta="quanto somar/subtrair (ex: -1)", usuario="(opcional) alvo; só Mestre/Admin")
async def personagem_condicao(interaction: discord.Interaction, delta: int, usuario: Optional[discord.Member] = None):
    if not interaction.guild:
        await interaction.response.send_message("Use esse comando dentro de um servidor.", ephemeral=True)
        return

    if usuario and not is_master(interaction.user):  # type: ignore[arg-type]
        await interaction.response.send_message("Só Mestre/Admin pode alterar condição de outros.", ephemeral=True)
        return

    target = usuario or interaction.user  # type: ignore[assignment]
    data = await load_data()
    uid = str(target.id)
    char = data.get(uid)
    if not char:
        await interaction.response.send_message("Esse usuário ainda não tem ficha criada.", ephemeral=True)
        return

    char = ensure_char_defaults(char)
    cond = char.get("condition", {"current": 0, "max": DEFAULT_CONDITION_MAX})
    cond["max"] = int(cond.get("max", DEFAULT_CONDITION_MAX))
    cond["current"] = max(0, min(cond["max"], int(cond.get("current", cond["max"])) + int(delta)))
    char["condition"] = cond
    char["updated_at"] = utc_now_iso()
    data[uid] = char
    await save_data(data)

    await interaction.response.send_message(
        f"✅ Condição de **{target.display_name}** agora é **{cond['current']}/{cond['max']}**.",
        ephemeral=True
    )

@tree.command(name="personagem_ruptura", description="Marca um Fato como rompido (não pode mais usar).")
@app_commands.describe(usuario="(opcional) alvo; só Mestre/Admin")
async def personagem_ruptura(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    if not interaction.guild:
        await interaction.response.send_message("Use esse comando dentro de um servidor.", ephemeral=True)
        return

    if usuario and not is_master(interaction.user):  # type: ignore[arg-type]
        await interaction.response.send_message("Só Mestre/Admin pode aplicar ruptura em outro usuário.", ephemeral=True)
        return

    target = usuario or interaction.user  # type: ignore[assignment]
    data = await load_data()
    uid = str(target.id)
    char = data.get(uid)
    if not char:
        await interaction.response.send_message("Esse usuário ainda não tem ficha criada.", ephemeral=True)
        return

    char = ensure_char_defaults(char)
    options_pairs = list_fact_options_not_ruptured(char)
    if not options_pairs:
        await interaction.response.send_message("Não há fatos disponíveis para romper (ou todos já estão rompidos).", ephemeral=True)
        return

    view = RupturaView(requester_id=interaction.user.id, target_user_id=uid, options_pairs=options_pairs)
    await interaction.response.send_message(
        f"Escolha qual fato de **{target.display_name}** vai sofrer **ruptura**:",
        ephemeral=True,
        view=view
    )

@tree.command(name="personagem_descansar", description="Descanso: recupera fatos rompidos (limpa rupturas).")
@app_commands.describe(usuario="(opcional) alvo; só Mestre/Admin")
async def personagem_descansar(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    if not interaction.guild:
        await interaction.response.send_message("Use esse comando dentro de um servidor.", ephemeral=True)
        return

    if usuario and not is_master(interaction.user):  # type: ignore[arg-type]
        await interaction.response.send_message("Só Mestre/Admin pode dar descanso para outro usuário.", ephemeral=True)
        return

    target = usuario or interaction.user  # type: ignore[assignment]
    data = await load_data()
    uid = str(target.id)
    char = data.get(uid)
    if not char:
        await interaction.response.send_message("Esse usuário ainda não tem ficha criada.", ephemeral=True)
        return

    char = ensure_char_defaults(char)
    ruptured = char.get("ruptured_facts", [])
    if not ruptured:
        await interaction.response.send_message("Nenhum fato estava rompido. ✅", ephemeral=True)
        return

    char["ruptured_facts"] = []
    char["updated_at"] = utc_now_iso()
    data[uid] = char
    await save_data(data)

    await interaction.response.send_message(
        f"🛌 Descanso aplicado! **{len(ruptured)}** fato(s) recuperado(s) para **{target.display_name}**.",
        ephemeral=True
    )

@tree.command(name="personagem_novo_fato", description="Gasta 3 XP para criar um novo fato.")
@app_commands.describe(usuario="(opcional) alvo; só Mestre/Admin")
async def personagem_novo_fato(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    if not interaction.guild:
        await interaction.response.send_message("Use esse comando dentro de um servidor.", ephemeral=True)
        return

    if usuario and not is_master(interaction.user):  # type: ignore[arg-type]
        await interaction.response.send_message("Só Mestre/Admin pode adicionar fato para outro usuário.", ephemeral=True)
        return

    target = usuario or interaction.user  # type: ignore[assignment]
    data = await load_data()
    uid = str(target.id)
    char = data.get(uid)
    if not char:
        await interaction.response.send_message("Esse usuário ainda não tem ficha criada.", ephemeral=True)
        return

    char = ensure_char_defaults(char)
    xp = int(char.get("xp", 0))
    if xp < XP_COST_NEW_FACT:
        await interaction.response.send_message(
            f"Você precisa de **3 XP** para criar um novo fato. XP atual de **{target.display_name}**: **{xp}**.",
            ephemeral=True
        )
        return

    view = TimelineView(requester_id=interaction.user.id, target_user_id=uid)
    await interaction.response.send_message(
        f"🎯 **Novo fato** (custa 3 XP). XP atual de **{target.display_name}**: **{xp}**.\n"
        "Escolha onde adicionar:",
        ephemeral=True,
        view=view
    )

@tree.command(name="personagem_editar_fato", description="Edita um fato já salvo (corrigir digitação).")
@app_commands.describe(usuario="(opcional) alvo; só Mestre/Admin")
async def personagem_editar_fato(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    if not interaction.guild:
        await interaction.response.send_message("Use esse comando dentro de um servidor.", ephemeral=True)
        return

    if usuario and not is_master(interaction.user):  # type: ignore[arg-type]
        await interaction.response.send_message("Só Mestre/Admin pode editar fatos de outro usuário.", ephemeral=True)
        return

    target = usuario or interaction.user  # type: ignore[assignment]
    data = await load_data()
    uid = str(target.id)
    char = data.get(uid)
    if not char:
        await interaction.response.send_message("Esse usuário ainda não tem ficha criada.", ephemeral=True)
        return

    char = ensure_char_defaults(char)
    options_pairs = list_all_fact_options(char)
    if not options_pairs:
        await interaction.response.send_message("Esse personagem não tem fatos para editar.", ephemeral=True)
        return

    view = EditarFatoView(requester_id=interaction.user.id, target_user_id=uid, options_pairs=options_pairs)
    await interaction.response.send_message(
        f"✏️ Escolha o fato de **{target.display_name}** que você quer editar:",
        ephemeral=True,
        view=view
    )

# ---------------- Ready / Sync ----------------

@client.event
async def on_ready():
    print("ON_READY disparou")
    synced = await tree.sync()
    print(f"Sincronizados: {len(synced)} comandos")

# ---------------- Main ----------------

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Defina a env DISCORD_BOT_TOKEN com o token do bot.")
    client.run(TOKEN)
