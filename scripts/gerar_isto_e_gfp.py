"""
Gera `isto-e-gfp.qmd` a partir de "O que é PFM.docx", a tradução integral do
artigo "This is PFM" (Andrews, Cangiano, Cole, de Renzio, Krause e
Seligmann, Harvard Kennedy School, 2014).

A figura 1 do original está em inglês. O documento traduzido traz, logo a
seguir à imagem, a lista dos rótulos em português. Este script substitui as
duas coisas por um diagrama redesenhado em SVG com os termos em português —
texto a sério, que acompanha o tema escuro e se lê em qualquer tamanho de
ecrã — e guarda a imagem original num bloco recolhível, para quem queira
confrontar.

A ordem das caixas da base (6, 5, 4 da esquerda para a direita) é a do
original e não é arbitrária: segue o sentido do ciclo, que na base corre da
direita para a esquerda.

Uso:
    python scripts/gerar_isto_e_gfp.py
"""

import html
import re
import shutil
import subprocess
import tempfile
import unicodedata
import zipfile
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

RAIZ = Path(__file__).resolve().parent.parent
FONTE = next(
    (p for p in (RAIZ / "materiais_de_referencia").glob("*.docx")
     if "PFM" in unicodedata.normalize("NFC", p.name)),
    None,
)
SAIDA = RAIZ / "isto-e-gfp.qmd"
IMG_ORIG = RAIZ / "figuras" / "gfp-ciclo-original-en.png"

NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

# O original vive na pasta do Google Drive partilhada com o grupo de trabalho.
LINK_ORIGINAL = ("https://drive.google.com/file/d/"
                 "1cHOXDeBl9pxa9CX_CCdcKevVmFYR4L44/view?usp=drive_link")

# A nota de abertura do .docx passa a remeter para o original.
NOTA_DE = "Segue a tradução integral do documento"
NOTA_PARA = f"Tradução integral do documento [This is PFM]({LINK_ORIGINAL})"

# O bloco de rótulos da figura, que o SVG passa a dispensar: vai do parágrafo
# que o abre até ao primeiro parágrafo do corpo que se lhe segue.
ABRE_ROTULOS = "(Representação do ciclo"
FECHA_ROTULOS = "Como a figura sugere"


def abrir(caminho):
    try:
        return docx.Document(caminho)
    except PermissionError:
        tmp = Path(tempfile.gettempdir()) / f"_hiip_{caminho.name}"
        try:
            shutil.copy2(caminho, tmp)
        except PermissionError:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Copy-Item -LiteralPath '{caminho}' -Destination '{tmp}' -Force"],
                check=True, capture_output=True)
        print("  (documento aberto noutro programa; li uma cópia)")
        return docx.Document(tmp)


def segmentos(p):
    out = []
    for r in p.runs:
        if not r.text:
            continue
        f = (bool(r.bold), bool(r.italic))
        if out and out[-1][1:] == f:
            out[-1] = (out[-1][0] + r.text, *f)
        else:
            out.append((r.text, *f))
    return out


def md(segs):
    """Segmentos -> markdown, com negrito e itálico."""
    s = ""
    for t, b, i in segs:
        t = t.replace("*", r"\*")
        if b and t.strip():
            t = f"**{t.strip()}**" + (" " if t.endswith(" ") else "")
        elif i and t.strip():
            t = f"*{t.strip()}*" + (" " if t.endswith(" ") else "")
        s += t
    return re.sub(r"\s+", " ", s).strip()


def celula(s):
    return re.sub(r"\s+", " ", s).strip().replace("|", "\\|")


def e_lista(ch):
    pPr = ch.find(f"{NS_W}pPr")
    return pPr is not None and pPr.find(f"{NS_W}numPr") is not None


# --------------------------------------------------------------- o diagrama
ETAPAS = [
    # (x, y, largura, título da etapa)
    (330, 6, 300, "FORMULAÇÃO DO ORÇAMENTO"),
    (700, 110, 260, "APROVAÇÃO DO ORÇAMENTO"),
    (330, 300, 300, "EXECUÇÃO DO ORÇAMENTO"),
    (0, 110, 260, "AVALIAÇÃO DO ORÇAMENTO"),
]

CAIXAS = [
    # (x, y, largura, altura, linhas de texto)
    (332, 40, 146, 54, ["1. Orçamentação", "Estratégica"]),
    (484, 40, 146, 54, ["2. Preparação do", "Orçamento"]),
    (700, 144, 260, 54, ["3. Debate Legislativo", "e Aprovação"]),
    (252, 334, 156, 62, ["6. Contabilidade e", "Prestação de Contas"]),
    (412, 334, 156, 62, ["5. Controlo/Auditoria", "Interna"]),
    (572, 334, 156, 62, ["4. Gestão de Recursos"]),
    (0, 144, 260, 54, ["7. Auditoria Externa", "e Responsabilização"]),
]

# As setas correm nos quatro cantos livres, entre blocos, no sentido do ciclo.
# Curvas quadráticas: mais fáceis de manter dentro do espaço vazio do que
# arcos de circunferência, que passavam por trás das caixas.
ARCOS = [
    "M 648,24 Q 762,38 768,100",     # formulação -> aprovação
    "M 772,206 Q 764,292 702,316",   # aprovação -> execução
    "M 262,316 Q 198,292 190,206",   # execução -> avaliação
    "M 190,100 Q 198,38 312,24",     # avaliação -> formulação
]


def svg():
    p = ['<svg class="gfp-fig" viewBox="0 0 960 406" role="img" '
         'aria-label="Ciclo do sistema de gestão das finanças públicas, '
         'com quatro etapas e sete processos">',
         '<defs><marker id="gfp-seta" viewBox="0 0 10 10" refX="8" refY="5" '
         'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
         '<path d="M 0 0 L 10 5 L 0 10 z" class="pt"/></marker></defs>']
    for d in ARCOS:
        p.append(f'<path class="arw" d="{d}" marker-end="url(#gfp-seta)"/>')
    for x, y, w, t in ETAPAS:
        p.append(f'<rect class="st" x="{x}" y="{y}" width="{w}" height="30" rx="3"/>')
        p.append(f'<text class="st-t" x="{x + w / 2}" y="{y + 20}" '
                 f'text-anchor="middle">{html.escape(t)}</text>')
    for x, y, w, h, linhas in CAIXAS:
        p.append(f'<rect class="bx" x="{x}" y="{y}" width="{w}" height="{h}" rx="3"/>')
        base = y + h / 2 - (len(linhas) - 1) * 9 + 5
        for k, l in enumerate(linhas):
            p.append(f'<text class="bx-t" x="{x + w / 2}" y="{base + k * 18}" '
                     f'text-anchor="middle">{html.escape(l)}</text>')
    p.append('<text class="ctr" x="480" y="216" text-anchor="middle">Sistema de GFP</text>')
    p.append("</svg>")
    return "\n".join(p)


def arejar(linhas):
    """Garante uma linha em branco antes de cada título.

    Um `## Título` logo a seguir a um item de lista, sem linha em branco no
    meio, não é lido como título: fica texto do item.
    """
    out = []
    for l in linhas:
        if l.lstrip().startswith("#") and out and out[-1].strip():
            out.append("")
        out.append(l)
    return out


def main():
    if FONTE is None:
        raise SystemExit("documento não encontrado em materiais_de_referencia/")
    d = abrir(FONTE)

    # a imagem original, guardada para o bloco de confronto
    IMG_ORIG.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(FONTE) as z:
        media = [n for n in z.namelist() if n.startswith("word/media/")]
        if media:
            IMG_ORIG.write_bytes(z.read(media[0]))

    o, ti = [], 0
    titulo = nota = None
    estado = "corpo"
    saltados = 0

    for ch in d.element.body.iterchildren():
        tag = ch.tag.split("}")[-1]

        if tag == "tbl":
            t = Table(ch, d)
            filas = []
            for row in t.rows:
                vals, vistos = [], set()
                for c in row.cells:
                    if c._tc in vistos:
                        continue
                    vistos.add(c._tc)
                    vals.append(celula(c.text))
                if any(vals):
                    filas.append(vals)
            if filas:
                n = max(len(f) for f in filas)
                o.append("| " + " | ".join((filas[0] + [""] * n)[:n]) + " |")
                o.append("|" + "|".join([":--"] * n) + "|")
                for f in filas[1:]:
                    o.append("| " + " | ".join((f + [""] * n)[:n]) + " |")
                o.append('\n: {tbl-colwidths="[56,22,22]"}\n')
            ti += 1
            continue

        if tag != "p":
            continue

        p = Paragraph(ch, d)
        texto = re.sub(r"\s+", " ", p.text).strip()
        estilo = p.style.name if p.style is not None else ""
        tem_img = bool(ch.findall(f".//{NS_A}blip"))

        # o bloco de rótulos da figura é substituído pelo diagrama
        if estado == "rotulos":
            if texto.startswith(FECHA_ROTULOS):
                estado = "corpo"
            else:
                if texto:
                    saltados += 1
                continue
        if texto.startswith(ABRE_ROTULOS):
            estado = "rotulos"
            saltados += 1
            continue

        if tem_img:
            o.append("```{=html}")
            o.append(svg())
            o.append("```\n")
            o.append(
                '::: {.callout-note collapse="true" title="A figura original, em inglês"}\n'
                f'![]({IMG_ORIG.parent.name}/{IMG_ORIG.name})\n\n'
                "Andrews M, Cangiano M, Cole N, de Renzio P, Krause P, Seligmann R. "
                "*This is PFM.* Harvard Kennedy School, Faculty Research Working "
                "Paper Series, julho de 2014.\n:::\n")
            continue

        if not texto:
            continue

        if estilo == "Heading 1":
            titulo = texto
        elif estilo.startswith("Heading"):
            nivel = "##" if estilo == "Heading 3" else "###"
            o.append(f"{nivel} {texto}\n")
        elif titulo is None and nota is None:
            nota = md(segmentos(p))          # a linha que apresenta a tradução
        elif e_lista(ch):
            o.append(f"- {md(segmentos(p))}")
        else:
            o.append(md(segmentos(p)) + "\n")

    cab = ["---", f'title: "Isto é GFP (This is PFM)"',
           'subtitle: "Tradução integral do artigo de Andrews e colegas, 2014"',
           "---", ""]
    if nota:
        if NOTA_DE in nota:
            nota = nota.replace(NOTA_DE, NOTA_PARA, 1)
        else:
            print(f"  AVISO: a nota de abertura mudou; o link para o original "
                  f"não foi inserido. Começa por: {nota[:60]!r}")
        cab.append(f"*{nota}*\n")

    SAIDA.write_text("\n".join(arejar(cab + o)), encoding="utf-8")
    print(f"Escrito: {SAIDA}")
    print(f"  título: {titulo}")
    print(f"  {sum(1 for l in o if l.startswith('## '))} secções, "
          f"{sum(1 for l in o if l.startswith('- '))} itens de lista, "
          f"{ti} tabela(s)")
    print(f"  {saltados} parágrafos de rótulos substituídos pelo diagrama")
    print(f"  figura original guardada em {IMG_ORIG.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
