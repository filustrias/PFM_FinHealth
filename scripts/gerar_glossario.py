"""
Gera `glossario.qmd` a partir de `glossario.yml`.

A página tem três coisas que o PDF não pode ter: um filtro que reduz a lista
enquanto se escreve, navegação A–Z, e uma âncora por termo. As âncoras são o
contrato com a fase seguinte — o ligador automático de termos no corpo do
livro aponta para elas, e um `#g-...` no endereço abre a entrada respectiva.

As definições vêm fechadas, para a página abrir como um índice consultável.
Para as ter abertas por omissão, mudar ABERTO_POR_OMISSAO para True.

Uso:
    python scripts/gerar_glossario.py
"""

import html
import json
import re
import unicodedata
from collections import OrderedDict
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "glossario.yml"
EXTRAS = RAIZ / "glossario_comentarios.yml"   # camada editorial (opcional)
SAIDA = RAIZ / "glossario.qmd"

ABERTO_POR_OMISSAO = False


def sem_acento(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


REF = re.compile(r"\[\[(g-[a-z0-9-]+)\|([^\]]+)\]\]")


def texto_html(s, ids):
    """Escapa o texto e converte [[g-id|texto]] em ligação para a entrada."""
    def troca(m):
        alvo, rot = m.group(1), m.group(2)
        if alvo not in ids:
            print(f"  AVISO: referência para entrada inexistente: {alvo}")
            return rot
        return f'<a href="#{alvo}">{rot}</a>'
    return REF.sub(troca, html.escape(" ".join(s.split())))


def sem_refs(s):
    return REF.sub(lambda m: m.group(2), s)


def letra(termo):
    ini = sem_acento(termo)[:1].upper()
    return ini if ini.isalpha() else "#"


def main():
    d = yaml.safe_load(DADOS.read_text(encoding="utf-8"))
    entradas = [dict(e) for e in d["entradas"]]

    # ---------------------------------------------------- camada editorial
    extras = {}
    if EXTRAS.exists():
        extras = yaml.safe_load(EXTRAS.read_text(encoding="utf-8")) or {}
    ids = {e["id"] for e in entradas}
    for nova in extras.get("novas") or []:
        if nova["id"] in ids:
            print(f"  AVISO: termo novo repete um id existente: {nova['id']}")
            continue
        entradas.append(dict(nova, origem="FinHealth"))
        ids.add(nova["id"])
    for chave, extra in (extras.get("comentarios") or {}).items():
        alvo = next((e for e in entradas if e["id"] == chave), None)
        if alvo is None:
            print(f"  AVISO: comentário para entrada inexistente: {chave}")
            continue
        alvo.update(extra)
    entradas.sort(key=lambda e: sem_acento(e["termo"]))

    grupos = OrderedDict()
    for e in entradas:
        grupos.setdefault(letra(e["termo"]), []).append(e)

    o = ["---", 'title: "Glossário"',
         'subtitle: "Gestão das finanças públicas para a saúde"', "---", ""]

    # ---------------------------------------------------- preâmbulo
    for p in d.get("preambulo", []):
        if p["rotulo"] == "Sobre Este Documento":
            o.append(f'::: {{.callout-note title="{p["rotulo"]}"}}')
            o.append(p["texto"])
            o.append(":::\n")
        else:
            o.append(f'**{p["rotulo"]}.** {p["texto"]}\n')

    # ---------------------------------------------------- controlos
    az = "".join(
        f'<a href="#gl-{l}" data-letter="{l}">{l}</a>' for l in grupos
    )
    o.append("```{=html}")
    o.append(
        '<div class="gl-controls">'
        '<input id="gl-filter" type="search" autocomplete="off" '
        'placeholder="Filtrar por termo, equivalente em inglês ou definição…" '
        'aria-label="Filtrar o glossário">'
        f'<span class="gl-count"><b id="gl-n">{len(entradas)}</b> '
        f'<span id="gl-n-label">termos</span></span>'
        '<button id="gl-toggle" type="button" class="gl-btn">Abrir tudo</button>'
        "</div>"
        f'<nav class="gl-az" aria-label="Navegação alfabética">{az}</nav>'
    )

    # ---------------------------------------------------- entradas
    o.append('<div class="gl-list">')
    for l, itens in grupos.items():
        o.append(f'<section class="gl-group" id="gl-{l}" data-letter="{l}">')
        o.append(f'<h3 class="gl-letter" aria-hidden="true">{l}</h3>')
        for e in itens:
            extra_b = " ".join(sem_refs(e.get(k, "")) for k in ("comentario", "divergencia"))
            busca = sem_acento(f'{e["termo"]} {e["ingles"]} {e["definicao"]} {extra_b}'.strip())
            origem = (' <span class="gl-orig">(FinHealth)</span>'
                      if e.get("origem") == "FinHealth" else "")
            corpo = f'<p>{html.escape(" ".join(e["definicao"].split()))}</p>'
            if e.get("fonte"):
                corpo += f'<p class="gl-fonte">Fonte: {html.escape(e["fonte"])}</p>'
            if e.get("comentario"):
                corpo += f'<p class="gl-coment">{texto_html(e["comentario"], ids)}</p>'
            if e.get("divergencia"):
                corpo += (f'<p class="gl-diverg"><span class="gl-diverg-rot">'
                          f'Divergência.</span> {texto_html(e["divergencia"], ids)}</p>')
            termo_b = sem_acento(e["termo"])
            o.append(
                f'<details class="gl-item" id="{e["id"]}"'
                f'{" open" if ABERTO_POR_OMISSAO else ""} '
                f'data-b="{html.escape(busca, quote=True)}" '
                f'data-t="{html.escape(termo_b, quote=True)}">'
                f'<summary><span class="gl-term">{html.escape(e["termo"])}{origem}</span>'
                f'<span class="gl-en">{html.escape(e["ingles"])}</span></summary>'
                f'{corpo}</details>'
            )
        o.append("</section>")
    o.append("</div>")

    # ---------------------------------------------------- comportamento
    o.append(GUIAO)
    o.append("```")

    SAIDA.write_text("\n".join(o), encoding="utf-8")
    n_lig = sum(1 for e in entradas if e.get("ligar"))
    n_com = sum(1 for e in entradas if e.get("comentario"))
    n_div = sum(1 for e in entradas if e.get("divergencia"))
    n_fh = sum(1 for e in entradas if e.get("origem") == "FinHealth")
    print(f"Escrito: {SAIDA}")
    print(f"  {n_com} comentários, {n_div} notas de divergência, "
          f"{n_fh} termos acrescentados do FinHealth")
    print(f"  {len(entradas)} termos em {len(grupos)} letras "
          f"({n_lig} marcados para ligação automática)")


GUIAO = """<script>
(function () {
  const norm = s => s.normalize("NFKD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
  const campo = document.getElementById("gl-filter");
  const conta = document.getElementById("gl-n");
  const rotulo = document.getElementById("gl-n-label");
  const botao = document.getElementById("gl-toggle");
  const itens = Array.from(document.querySelectorAll(".gl-item"));
  const grupos = Array.from(document.querySelectorAll(".gl-group"));
  const total = itens.length;

  function filtrar() {
    const q = norm(campo.value.trim());
    let n = 0;
    for (const it of itens) {
      const ok = !q || it.dataset.b.includes(q);
      it.hidden = !ok;
      if (ok) {
        n++;
        // se o termo não bate mas a definição bate, abre para mostrar porquê
        if (q.length >= 2 && !it.dataset.t.includes(q)) it.open = true;
        else if (q) it.open = false;
      }
    }
    for (const g of grupos) {
      const visivel = g.querySelector(".gl-item:not([hidden])") !== null;
      g.hidden = !visivel;
      const a = document.querySelector('.gl-az a[data-letter="' + g.dataset.letter + '"]');
      if (a) a.classList.toggle("gl-off", !visivel);
    }
    conta.textContent = n;
    rotulo.textContent = (q ? (n === 1 ? "termo encontrado" : "termos encontrados")
                            : (n === 1 ? "termo" : "termos"));
  }

  campo.addEventListener("input", filtrar);
  campo.addEventListener("keydown", e => {
    if (e.key === "Escape") { campo.value = ""; filtrar(); }
  });

  botao.addEventListener("click", () => {
    const abrir = botao.dataset.estado !== "aberto";
    itens.filter(i => !i.hidden).forEach(i => { i.open = abrir; });
    botao.dataset.estado = abrir ? "aberto" : "fechado";
    botao.textContent = abrir ? "Fechar tudo" : "Abrir tudo";
  });

  // Uma ligação para #g-... abre a entrada e leva-a para o ecrã.
  function abrirAlvo() {
    const id = decodeURIComponent(location.hash.replace("#", ""));
    if (!id) return;
    const alvo = document.getElementById(id);
    if (alvo && alvo.classList.contains("gl-item")) {
      alvo.open = true;
      alvo.classList.add("gl-alvo");
      alvo.scrollIntoView({ block: "center" });
      setTimeout(() => alvo.classList.remove("gl-alvo"), 2200);
    }
  }
  window.addEventListener("hashchange", abrirAlvo);
  abrirAlvo();
})();
</script>"""


if __name__ == "__main__":
    main()
