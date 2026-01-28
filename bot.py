import os
import discord
from discord import app_commands

import rpg_core as core

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.dm_messages = True
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ============================================================
# Criação e consulta
# ============================================================

@tree.command(name="criar_personagem", description="Cria uma ficha (regras novas) via wizard por DM.")
async def criar_personagem(interaction: discord.Interaction):
    await interaction.response.send_message("Te chamei na DM para criar sua ficha. 📩", ephemeral=True)

    char = await core.run_character_wizard(client, interaction.user)
    if not char:
        try:
            dm = interaction.user.dm_channel or await interaction.user.create_dm()
            await dm.send("⏳ Wizard cancelado/expirou. Use `/criar_personagem` de novo quando quiser.")
        except Exception:
            pass
        return

    await core.save_character(interaction.user.id, char)


@tree.command(name="ficha", description="Mostra sua ficha (ou a de alguém, se você for Mestre/Admin).")
@app_commands.describe(usuario="Opcional: ver ficha de outro usuário (apenas Mestre/Admin).")
async def ficha(interaction: discord.Interaction, usuario: discord.User | None = None):
    target = usuario or interaction.user

    if usuario and interaction.guild and isinstance(interaction.user, discord.Member):
        if not core.is_master(interaction.user):
            await interaction.response.send_message("Você não tem permissão para ver a ficha de outra pessoa.", ephemeral=True)
            return

    char = await core.get_character(target.id)
    if not char:
        await interaction.response.send_message("Nenhuma ficha encontrada. Use `/criar_personagem`.", ephemeral=True)
        return

    await interaction.response.send_message(core.render_character(char), ephemeral=True)

# ============================================================
# NOVOS COMANDOS pedidos
# ============================================================

@tree.command(name="personagem_editar_fato", description="Edita um fato do seu personagem (por DM).")
async def personagem_editar_fato(interaction: discord.Interaction):
    await interaction.response.send_message("Te chamei na DM para editar um fato. 📩", ephemeral=True)
    ok, msg = await core.edit_fact_flow(client, interaction.user)
    try:
        dm = interaction.user.dm_channel or await interaction.user.create_dm()
        await dm.send(("✅ " if ok else "❌ ") + msg)
    except Exception:
        pass


@tree.command(name="personagem_novo_fato", description="Gasta XP para adicionar um novo fato (por DM).")
async def personagem_novo_fato(interaction: discord.Interaction):
    await interaction.response.send_message("Te chamei na DM para adicionar um novo fato. 📩", ephemeral=True)
    ok, msg = await core.add_fact_with_xp(client, interaction.user)
    try:
        dm = interaction.user.dm_channel or await interaction.user.create_dm()
        await dm.send(("✅ " if ok else "❌ ") + msg)
    except Exception:
        pass


@tree.command(name="personagem_descansar", description="Descansa e restaura PV/PM/Destino ao máximo.")
async def personagem_descansar(interaction: discord.Interaction):
    ok, msg = await core.rest_character(interaction.user.id)
    await interaction.response.send_message(("✅ " if ok else "❌ ") + msg, ephemeral=True)


@tree.command(name="personagem_ruptura", description="Escolhe um fato e realiza Ruptura (por DM).")
async def personagem_ruptura(interaction: discord.Interaction):
    await interaction.response.send_message("Te chamei na DM para fazer uma ruptura. 📩", ephemeral=True)
    ok, msg = await core.rupture_fact_flow(interaction.user)
    try:
        dm = interaction.user.dm_channel or await interaction.user.create_dm()
        await dm.send(("✅ " if ok else "❌ ") + msg)
    except Exception:
        pass


@tree.command(name="personagem_condicao", description="Mostra suas reservas (PV/PM/Destino).")
async def personagem_condicao(interaction: discord.Interaction):
    ok, msg = await core.get_condition_text(interaction.user.id)
    await interaction.response.send_message(("✅ " if ok else "❌ ") + msg, ephemeral=True)


@tree.command(name="personagem_xp", description="Mostra/ajusta XP. Jogador vê o seu; Mestre pode ajustar de qualquer um.")
@app_commands.describe(
    usuario="Opcional: alvo (apenas Mestre/Admin).",
    delta="Opcional: ajuste de XP (ex.: 1, -1, 5). Se não informar, só mostra."
)
async def personagem_xp(interaction: discord.Interaction, usuario: discord.User | None = None, delta: int | None = None):
    target = usuario or interaction.user

    # Ajuste (delta) só se for dono ou mestre/admin
    if delta is not None:
        if target.id != interaction.user.id:
            if not (interaction.guild and isinstance(interaction.user, discord.Member) and core.is_master(interaction.user)):
                await interaction.response.send_message("Você não tem permissão para ajustar XP de outra pessoa.", ephemeral=True)
                return

        ok, msg = await core.xp_adjust(target.id, int(delta))
        await interaction.response.send_message(("✅ " if ok else "❌ ") + msg, ephemeral=True)
        return

    # Só mostrar XP
    char = await core.get_character(target.id)
    if not char:
        await interaction.response.send_message("Nenhuma ficha encontrada.", ephemeral=True)
        return
    await interaction.response.send_message(f"XP de **{char.get('name','—')}**: **{char.get('xp',0)}**", ephemeral=True)


# ============================================================
# Utilitários
# ============================================================

@tree.command(name="reset_sessao", description="Reseta sessão travada do wizard (apenas Mestre/Admin).")
async def reset_sessao(interaction: discord.Interaction, usuario: discord.User):
    if interaction.guild and isinstance(interaction.user, discord.Member):
        if not core.is_master(interaction.user):
            await interaction.response.send_message("Sem permissão.", ephemeral=True)
            return

    core.active_sessions.pop(usuario.id, None)
    await interaction.response.send_message("✅ Sessão resetada.", ephemeral=True)


@client.event
async def on_ready():
    try:
        await tree.sync()
    except Exception as e:
        print("Erro ao sync:", e)
    print(f"Logado como {client.user}.")


def main():
    if not TOKEN:
        raise SystemExit("Defina DISCORD_BOT_TOKEN no ambiente.")
    client.run(TOKEN)


if __name__ == "__main__":
    main()
