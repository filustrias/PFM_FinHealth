"""
Gera `isto-e-gfp.qmd` a partir do original de "This is PFM" (Andrews,
Cangiano, Cole, de Renzio, Krause e Seligmann, Harvard Kennedy School, 2014)
e da tradução do pipeline.

Como no FinHealth, a tradução vive em JSON por identificador de segmento
(`doc:<n>` = n-ésimo parágrafo do document.xml) e é aplicada ao original,
sem passar por um .docx traduzido.

O original vem de uma conversão de PDF, o que traz duas particularidades que
o pipeline resolve e que este script assume já resolvidas:

* os atributos de espaçamento de caracteres (`w:spacing`, `w:w`, `w:kern`)
  têm de ser removidos antes do `split`, senão o texto sai partido palavra a
  palavra;
* as quebras de página do PDF partiram parágrafos a meio. A tradução juntou
  cada um no primeiro pedaço, pelo que os pedaços seguintes — listados em
  `cont.json` — ficam sem tradução e são descartados aqui.

Preparação:

    python <pipeline>/tools/pipeline.py split <pasta_do_docx_desempacotado>

Uso:
    python scripts/gerar_isto_e_gfp.py <pasta> <tall.json> <cont.json> [<fig>]
"""

import html
import json
import re
import sys
from pathlib import Path

from lxml import etree

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "isto-e-gfp.qmd"
FIGURAS = RAIZ / "figuras"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
q = lambda t: f"{{{W}}}{t}"
NS = {"w": W}
IDX = "{urn:tipfm}i"

# O original está na pasta do Drive partilhada com o grupo de trabalho.
LINK_ORIGINAL = ("https://drive.google.com/file/d/"
                 "1cHOXDeBl9pxa9CX_CCdcKevVmFYR4L44/view?usp=drive_link")

NOTA = (f"*Tradução integral para português do artigo "
        f"[This is PFM]({LINK_ORIGINAL}), de Matt Andrews, Marco Cangiano, "
        f"Neil Cole, Paolo de Renzio, Philipp Krause e Renaud Seligmann "
        f"(Harvard Kennedy School, 2014).*")


def destag(s):
    partes = re.findall(r"<(\d+)>(.*?)</\1>", s, re.S)
    return "".join(t for _, t in sorted(partes, key=lambda x: int(x[0]))) if partes else s


def own_runs(p):
    out = []
    for r in p.iter(q("r")):
        a = r.getparent()
        ok = True
        while a is not p:
            if a.tag in (q("p"), q("txbxContent"), q("del")):
                ok = False
                break
            a = a.getparent()
        if ok and r.find(q("t")) is not None:
            out.append(r)
    return out


def escapar(s):
    return re.sub(r"([*_\[\]`])", r"\\\1", s)


def arejar(linhas):
    """Separa blocos que o Markdown juntaria.

    Sem linha em branco a seguir a um item de lista, tanto um título como um
    parágrafo são absorvidos pelo item: o título deixa de ser título e o
    parágrafo passa a fazer parte do ponto anterior.
    """
    out = []
    for l in linhas:
        anterior = out[-1] if out else ""
        if anterior.strip():
            titulo = l.lstrip().startswith("#")
            saiu_da_lista = (anterior.lstrip().startswith(("- ", "* "))
                             and l.strip()
                             and not l.lstrip().startswith(("- ", "* ")))
            if titulo or saiu_da_lista:
                out.append("")
        out.append(l)
    return out


class Doc:
    def __init__(self, pasta, traducoes, continuacoes, figs=None):
        self.pasta = Path(pasta)
        self.tr = json.load(open(traducoes, encoding="utf-8"))
        self.cont = set(json.load(open(continuacoes, encoding="utf-8")))
        self.figs = Path(figs) if figs else None
        self.root = etree.parse(str(self.pasta / "word" / "document.xml")).getroot()
        for i, p in enumerate(self.root.iter(q("p"))):
            p.set(IDX, str(i))
        rels = etree.parse(str(self.pasta / "word" / "_rels" / "document.xml.rels")).getroot()
        self.rels = {x.get("Id"): x.get("Target") for x in rels}
        self.copiadas = 0

    def idx(self, p):
        return p.get(IDX, "-1")

    def estilo(self, p):
        st = p.find("w:pPr/w:pStyle", NS)
        return st.get(q("val")) if st is not None else ""

    def lista(self, p):
        return p.find("w:pPr/w:numPr", NS) is not None

    def imagens(self, p):
        return [self.rels[b.get(f"{{{R}}}embed")]
                for b in p.iter(f"{{{A}}}blip")
                if b.get(f"{{{R}}}embed") in self.rels]

    def simples(self, p):
        v = self.tr.get(f"doc:{self.idx(p)}")
        if v:
            return " ".join(destag(v).split())
        return " ".join("".join(x.text or "" for x in p.iter(q("t"))).split())

    def inline(self, p):
        runs = own_runs(p)
        textos = ["".join(t.text or "" for t in r.findall(q("t"))) for r in runs]
        cheios = [k for k, t in enumerate(textos) if t]
        bruto = self.tr.get(f"doc:{self.idx(p)}")
        if bruto is not None:
            if len(cheios) == 1:
                partes = {cheios[0]: bruto}
            else:
                partes = {int(m.group(1)): m.group(2)
                          for m in re.finditer(r"<(\d+)>(.*?)</\1>", bruto, re.S)}
                if not partes:
                    partes = {cheios[0]: destag(bruto)}
        else:
            partes = {k: textos[k] for k in cheios}

        saida = []
        for k in cheios:
            txt = partes.get(k, "")
            if not txt:
                continue
            rpr = runs[k].find(q("rPr"))
            neg = rpr is not None and rpr.find(q("b")) is not None
            ital = rpr is not None and rpr.find(q("i")) is not None
            s = escapar(txt)
            nu = s.strip()
            if nu:
                pre, pos = s[: len(s) - len(s.lstrip())], s[len(s.rstrip()):]
                if neg:
                    nu = f"**{nu}**"
                if ital:
                    nu = f"*{nu}*"
                s = pre + nu + pos
            saida.append(s)
        return re.sub(r"[ \t]+", " ", "".join(saida)).strip()

    def figura(self, p):
        alvos = self.imagens(p)
        if not alvos:
            return []
        origem = self.pasta / "word" / alvos[0].replace("../", "")
        traduzida = None
        if self.figs:
            traduzida = next(iter(sorted(self.figs.glob("image1.*"))), None)
        out = []
        if traduzida and traduzida.exists():
            destino = FIGURAS / f"gfp-ciclo-pt{traduzida.suffix}"
            destino.write_bytes(traduzida.read_bytes())
            self.copiadas += 1
            out += [f'![]({FIGURAS.name}/{destino.name}){{fig-align="center"}}', ""]
        # a original em inglês fica à mão, para confronto
        orig_destino = FIGURAS / "gfp-ciclo-original-en.png"
        orig_destino.write_bytes(origem.read_bytes())
        out += ['::: {.callout-note collapse="true" title="A figura original, em inglês"}',
                "",
                f"![]({FIGURAS.name}/{orig_destino.name})",
                "",
                ":::",
                ""]
        return out


def tabela(doc, tbl):
    filas = []
    for tr_ in tbl.findall(q("tr")):
        cel = []
        for tc in tr_.findall(q("tc")):
            ps = [doc.simples(p) for p in tc.iter(q("p"))]
            cel.append(" ".join(x for x in ps if x).replace("|", "\\|"))
        if any(cel):
            filas.append(cel)
    if not filas:
        return []
    n = max(len(f) for f in filas)
    filas = [(f + [""] * n)[:n] for f in filas]
    return (["| " + " | ".join(filas[0]) + " |", "|" + "|".join([":--"] * n) + "|"]
            + ["| " + " | ".join(f) + " |" for f in filas[1:]] + [""])


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    doc = Doc(*sys.argv[1:5])
    FIGURAS.mkdir(exist_ok=True)

    titulo, corpo = "Isto é GFP", []
    saltados = 0

    for el in doc.root.find(q("body")):
        tag = el.tag.split("}")[-1]
        if tag == "tbl":
            corpo += tabela(doc, el)
            continue
        if tag != "p":
            continue

        sid = f"doc:{doc.idx(el)}"
        if sid in doc.cont:        # pedaço partido pela quebra de página
            saltados += 1
            continue

        est = doc.estilo(el)
        texto = doc.inline(el)
        if doc.imagens(el):
            corpo += doc.figura(el)
            continue
        if not texto:
            continue

        if est == "Ttulo1":
            titulo = doc.simples(el)
        elif est == "Ttulo2":
            # as legendas das figuras estão marcadas como título, mas não o são
            if re.match(r"^\s*(Figura|Tabela|Quadro)\b", doc.simples(el)):
                corpo.append(f"**{doc.simples(el)}**\n")
            else:
                corpo.append(f"## {doc.simples(el)}\n")
        elif est == "Ttulo3":
            corpo.append(f"### {doc.simples(el)}\n")
        elif doc.lista(el):
            corpo.append(f"- {texto}")
        else:
            corpo.append(f"{texto}\n")

    cab = ["---", f'title: "{titulo} (This is PFM)"',
           'subtitle: "Andrews, Cangiano, Cole, de Renzio, Krause e Seligmann, 2014"',
           "---", "", NOTA, ""]
    texto = "\n".join(arejar(cab + corpo))
    texto = re.sub(r"\n{3,}", "\n\n", texto).rstrip() + "\n"
    SAIDA.write_text(texto, encoding="utf-8", newline="\n")

    print(f"Escrito: {SAIDA}")
    print(f"  título: {titulo}")
    print(f"  {sum(1 for l in corpo if l.startswith('## '))} secções, "
          f"{sum(1 for l in corpo if l.startswith('### '))} subsecções, "
          f"{sum(1 for l in corpo if l.startswith('- '))} itens de lista")
    print(f"  {saltados} pedaços de parágrafo partidos pela paginação, descartados")
    print(f"  {doc.copiadas} figura(s) traduzida(s) colocada(s)")


if __name__ == "__main__":
    main()
