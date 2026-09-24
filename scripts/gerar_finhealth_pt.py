"""
Gera os capítulos de `finhealth-pt/` a partir do documento original do
FinHealth 2.0 e das traduções do pipeline.

O pipeline de tradução guarda o texto em português em `traducoes/t*.json`,
por identificador de segmento (`doc:<n>` = n-ésimo parágrafo do
documento.xml; `fn:<n>` = notas de rodapé). Este script não passa pelo .docx
traduzido: lê o original, aplica a tradução parágrafo a parágrafo e escreve
Quarto directamente.

Antes de correr, é preciso desempacotar o original e normalizar os runs com
o próprio pipeline:

    python <pipeline>/tools/pipeline.py split <pasta_do_docx_desempacotado>

Uso:
    python scripts/gerar_finhealth_pt.py <pasta_desempacotada> <pasta_traducoes>

O texto traduzido não é alterado. O que este script faz é estrutura:
títulos, listas, tabelas, caixas, notas de rodapé, âncoras e ligações.
"""

import glob
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

pathlib_Path = Path

import yaml
from lxml import etree

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "finhealth-pt"
FIGURAS = RAIZ / "figuras"
GLOSSARIO = RAIZ / "glossario.yml"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
q = lambda t: f"{{{W}}}{t}"
NS = {"w": W}
IDX = "{urn:fh}i"

# Fronteiras dos capítulos, por índice de parágrafo no documento original.
# O título vem do próprio cabeçalho traduzido, excepto no primeiro capítulo,
# que começa na capa.
CAPITULOS = [
    ("01-introducao.qmd", "Introdução", 0, 94),
    ("02-realizacao-avaliacao.qmd", None, 94, 457),
    ("03-gargalos.qmd", None, 457, 1140),
    ("04-anexo-1.qmd", None, 1140, 1238),
    ("05-anexo-2.qmd", None, 1238, 1396),
    ("06-anexo-3.qmd", None, 1396, 1690),
    ("07-anexo-4.qmd", None, 1690, 10 ** 6),
]

# Ligação para o original, na pasta partilhada do grupo de trabalho.
LINK_ORIGINAL = ("https://docs.google.com/document/d/"
                 "15R0hMEkaFh_bleCE8-GR749pVo6ymtcv/edit?usp=drive_link")

AVISO = f"""::: {{.callout-warning title="Tradução de trabalho, não oficial"}}
Esta é uma tradução de trabalho da versão de Julho de 2026 do *FinHealth
Toolkit 2.0*, feita para apoiar as sessões do grupo técnico de trabalho. Não
é uma tradução oficial. Em caso de divergência, prevalece
[o original em inglês]({LINK_ORIGINAL}).

As decisões de tradução ainda em aberto estão reunidas em
[Problemas de tradução](../problemas-de-traducao.qmd).
:::
"""


# ----------------------------------------------------------------- util
def sem_acento(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def destag(s):
    partes = re.findall(r"<(\d+)>(.*?)</\1>", s, re.S)
    return "".join(t for _, t in sorted(partes, key=lambda x: int(x[0]))) if partes else s


def own_runs(p):
    """Runs de texto deste parágrafo, não de parágrafos aninhados."""
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


# --------------------------------------------------------------- modelo
class Doc:
    def __init__(self, pasta, traducoes, figs_pt=None):
        self.tr = {}
        for f in sorted(glob.glob(str(Path(traducoes) / "*.json"))):
            self.tr.update(json.load(open(f, encoding="utf-8")))
        self.root = etree.parse(str(Path(pasta) / "word" / "document.xml")).getroot()
        for i, p in enumerate(self.root.iter(q("p"))):
            p.set(IDX, str(i))
        self.notas = self._notas(Path(pasta))
        self.rels = self._rels(Path(pasta))
        self.pasta = Path(pasta)
        self.faltas = []
        self.copiadas = 0
        self.traduzidas = 0
        self.figs_pt = pathlib_Path(figs_pt) if figs_pt else None

    def _rels(self, pasta):
        r = etree.parse(str(pasta / "word" / "_rels" / "document.xml.rels")).getroot()
        return {x.get("Id"): x.get("Target") for x in r}

    def _notas(self, pasta):
        raiz = etree.parse(str(pasta / "word" / "footnotes.xml")).getroot()
        for i, p in enumerate(raiz.iter(q("p"))):
            p.set(IDX, str(i))
        out = {}
        for fn in raiz.iter(q("footnote")):
            fid = fn.get(q("id"))
            if fid in ("-1", "0"):
                continue
            pedacos = []
            for p in fn.iter(q("p")):
                t = self.tr.get(f"fn:{p.get(IDX)}")
                t = destag(t) if t else "".join(x.text or "" for x in p.iter(q("t")))
                if t.strip():
                    pedacos.append(" ".join(t.split()))
            if pedacos:
                out[fid] = " ".join(pedacos)
        return out

    def idx(self, p):
        return int(p.get(IDX, "-1"))

    def estilo(self, p):
        st = p.find("w:pPr/w:pStyle", NS)
        return st.get(q("val")) if st is not None else ""

    def lista(self, p):
        return p.find("w:pPr/w:numPr", NS) is not None

    def inline(self, p):
        """Markdown do parágrafo, com a tradução aplicada run a run."""
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
            # as referências bibliográficas ficam no original por decisão
            # de tradução; não contam como falha
            if "".join(textos).strip() and self.idx(p) < 1093:
                self.faltas.append(self.idx(p))

        # Percorre os runs pela ordem do documento para não perder os
        # tabuladores, que são runs próprios sem texto e separam a sigla da
        # sua expansão na lista de siglas.
        #
        # O negrito do original não é reproduzido: cobre um terço a metade do
        # texto, o que o torna ruído em vez de ênfase.
        pedacos = []
        for r in p.iter(q("r")):
            k = next((j for j, x in enumerate(runs) if x is r), None)
            if k is not None and k in cheios:
                txt = partes.get(k, "")
                if not txt:
                    continue
                rpr = runs[k].find(q("rPr"))
                ital = rpr is not None and rpr.find(q("i")) is not None
                s = escapar(txt)
                nu = s.strip()
                if nu and ital:
                    pre = s[: len(s) - len(s.lstrip())]
                    pos = s[len(s.rstrip()):]
                    s = pre + f"*{nu}*" + pos
                pedacos.append(s)
            elif r.find(q("tab")) is not None:
                pedacos.append("\t")
        texto = "".join(pedacos)

        # notas de rodapé, no ponto em que ocorrem
        for fr in p.iter(q("footnoteReference")):
            fid = fr.get(q("id"))
            if fid in self.notas:
                texto += f"[^{fid}]"
        # o tabulador só interessa na lista de siglas; no resto é um espaço
        return re.sub(r"[ ]+", " ", texto).strip()

    def texto_simples(self, p):
        t = self.tr.get(f"doc:{self.idx(p)}")
        if t:
            return " ".join(destag(t).split())
        return " ".join("".join(x.text or "" for x in p.iter(q("t"))).split())

    def figura_md(self, p):
        """Imagem da figura, preferindo a versão traduzida do pipeline."""
        alvos = self.imagens(p)
        if not alvos:
            return []
        origem = self.pasta / "word" / alvos[0].replace("../", "")
        traduzida = self.figs_pt / origem.name if self.figs_pt else None
        if traduzida and traduzida.exists():
            origem = traduzida
            self.traduzidas += 1
        destino = FIGURAS / f"finhealth-{origem.name}"
        destino.write_bytes(origem.read_bytes())
        self.copiadas += 1
        return [f'![](../{FIGURAS.name}/{destino.name}){{fig-align="center"}}', ""]

    def imagens(self, p):
        out = []
        for b in p.iter(f"{{{A}}}blip"):
            rid = b.get(f"{{{R}}}embed")
            if rid in self.rels:
                out.append(self.rels[rid])
        return out


# ------------------------------------------------------- figura 2.1
def mermaid_processo(titulos):
    """Figura 2.1 redesenhada, com os rótulos vindos dos títulos traduzidos."""
    def curto(t):
        t = re.sub(r"^\d+\.\d+\s*", "", t).strip().rstrip(":")
        return t[0].upper() + t[1:] if t else t

    # Nada de etiquetas HTML nem de rótulos começados por "N. ": o Mermaid
    # lê "1. " como início de lista numerada e escreve "Unsupported markdown"
    # no lugar do texto.
    p1, p2, p3, p4 = (curto(t) for t in titulos)
    # Sem subgraph: o agrupamento do Mermaid desenha um bloco escuro com
    # texto escuro, ilegível. A numeração 3.1 e 3.2 já mostra que as duas
    # tarefas pertencem à etapa 3.
    return f"""```{{mermaid}}
flowchart LR
  A["Etapa 1 — {p1}"] --> B["Etapa 2 — {p2}"]
  B --> C1["Etapa 3.1 — Identificar os gargalos"]
  C1 --> C2["Etapa 3.2 — Explorar as causas subjacentes dos gargalos de GFP"]
  C2 --> D["Etapa 4 — {p4}"]
  classDef causal stroke-dasharray: 5 3
  class C1,C2 causal
```

*As etapas 3.1 e 3.2, a tracejado, formam em conjunto a etapa 3, análise causal.*
"""


# ------------------------------------------------------------ tabelas
def tabela_md(doc, tbl):
    filas = []
    for tr_ in tbl.findall(q("tr")):
        celulas = []
        for tc in tr_.findall(q("tc")):
            ps = [doc.texto_simples(p) for p in tc.iter(q("p"))]
            celulas.append(" ".join(x for x in ps if x).replace("|", "\\|"))
        filas.append(celulas)
    # A Tabela 3.1 vem duplicada no original: a linha de cabeçalho repete-se
    # a meio. As duas cópias não são idênticas — a segunda omite o gargalo
    # 3.2.2 —, por isso fica a primeira, que é a completa.
    n = len(filas)
    if n >= 4 and n % 2 == 0 and filas[0] == filas[n // 2]:
        filas = filas[: n // 2]
    if not filas:
        return []
    largura = max(len(f) for f in filas)
    filas = [(f + [""] * largura)[:largura] for f in filas]
    out = ["| " + " | ".join(filas[0]) + " |",
           "|" + "|".join([":--"] * largura) + "|"]
    out += ["| " + " | ".join(f) + " |" for f in filas[1:]]
    out.append("")
    return out


def caixa_md(doc, tbl):
    """Tabela de uma só célula = caixa do documento.

    A Caixa 2.1 contém a figura 2.2, por isso as imagens são tratadas aqui e
    não apenas nos parágrafos soltos do corpo.
    """
    # Percorre os filhos da célula pela ordem em que estão: as caixas 2.2 e
    # 2.3 contêm tabelas aninhadas, que se perderiam se só se lessem os
    # parágrafos.
    linhas = []

    def percorrer(no):
        for filho in no:
            tag = filho.tag.split("}")[-1]
            if tag == "p":
                if doc.imagens(filho):
                    linhas.extend(doc.figura_md(filho))
                else:
                    l = doc.inline(filho)
                    if l:
                        linhas.append(l)
                        linhas.append("")
            elif tag == "tbl":
                cols = max(len(r.findall(q("tc"))) for r in filho.findall(q("tr")))
                linhas.extend(tabela_md(doc, filho) if cols > 1 else caixa_md(doc, filho))
            elif tag in ("tr", "tc"):
                percorrer(filho)

    percorrer(tbl)
    linhas = [l for l in linhas if l is not None]
    while linhas and not linhas[-1]:
        linhas.pop()
    if not linhas:
        return []
    # a primeira linha com texto é o título da caixa
    k = next((i for i, l in enumerate(linhas) if l.strip()), None)
    if k is None:
        return []
    titulo = re.sub(r"\*+", "", linhas[k]).replace('"', "'").strip()
    corpo = [l for l in linhas[k + 1:]]
    while corpo and not corpo[0]:
        corpo.pop(0)
    if not corpo:
        corpo, titulo = [titulo], "Caixa"
    return ([f'::: {{.callout-note title="{titulo[:150]}"}}', ""]
            + corpo + ["", ":::", ""])


# ------------------------------------------------------------- ligações
def ancora(num):
    return "sec-" + num.replace(".", "-")


def aplicar_remissoes(texto, ficheiro_actual):
    """(3.2.1) -> ligação para a âncora da secção."""
    destino = "" if ficheiro_actual == "03-gargalos.qmd" else "03-gargalos.qmd"

    def troca(m):
        num = m.group(1)
        return f"([{num}]({destino}#{ancora(num)}))"

    return re.sub(r"\((\d\.\d\.\d)\)", troca, texto)


def carregar_glossario():
    if not GLOSSARIO.exists():
        return []
    d = yaml.safe_load(GLOSSARIO.read_text(encoding="utf-8")) or {}
    termos = []
    for e in d.get("entradas", []):
        t = e["termo"].strip()
        # como no resto do livro, só termos específicos viram ligação:
        # siglas e termos compostos. Os genéricos cobririam o texto de azul.
        if (t.isupper() and 2 <= len(t) <= 8) or len(t.split()) >= 2:
            termos.append((t, e["id"]))
    termos.sort(key=lambda x: -len(x[0]))
    return termos


def ligar_glossario(linhas, termos):
    """Liga a primeira ocorrência de cada termo, uma vez por capítulo."""
    usados, n = set(), 0
    for i, linha in enumerate(linhas):
        if not linha or linha.startswith(("|", ":::", "```", "#", "[^")):
            continue
        for termo, tid in termos:
            if tid in usados:
                continue
            m = re.search(r"(?<![\w\[])(" + re.escape(termo) + r")(?![\w\]])",
                          linha, re.I)
            if m:
                linha = (linha[: m.start()] +
                         f"[{m.group(1)}](../glossario.qmd#{tid})" +
                         linha[m.end():])
                usados.add(tid)
                n += 1
        linhas[i] = linha
    return n


def tabelar_tabulacoes(linhas):
    """Transforma blocos separados por tabulador numa tabela.

    A lista de siglas do original usa tabuladores entre a sigla e o que ela
    significa. Em corrido ficariam encavaladas; em tabela lêem-se.
    """
    out, bloco = [], []

    def despejar():
        if not bloco:
            return
        if len(bloco) == 1:                      # um caso isolado não é tabela
            out.append(bloco[0].replace("\t", " — "))
        else:
            out.extend(["| Sigla | Significado |", "|:--|:--|"])
            for l in bloco:
                pedacos = [x.strip() for x in l.split("\t") if x.strip()]
                sigla = pedacos[0] if pedacos else ""
                resto = " ".join(pedacos[1:]).replace("|", "\\|")
                out.append(f"| **{sigla}** | {resto} |")
            out.extend(["", ': {tbl-colwidths="[16,84]"}', ""])
        bloco.clear()

    for l in linhas:
        if "\t" in l and l.strip():
            bloco.append(l.strip())
            continue
        if l.strip():
            despejar()
        out.append(l)
    despejar()
    return out


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


# ---------------------------------------------------------------- main
def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    doc = Doc(sys.argv[1], sys.argv[2],
              sys.argv[3] if len(sys.argv) > 3 else None)
    DESTINO.mkdir(exist_ok=True)
    FIGURAS.mkdir(exist_ok=True)

    # títulos das secções 2.x, para os rótulos da figura 2.1
    titulos2 = []
    for p in doc.root.iter(q("p")):
        if doc.estilo(p) == "Heading3" and 94 < doc.idx(p) < 457:
            titulos2.append(doc.texto_simples(p))

    body = doc.root.find(q("body"))
    saida = {nome: [] for nome, _, _, _ in CAPITULOS}
    notas_usadas = {nome: set() for nome, _, _, _ in CAPITULOS}

    def ficheiro_de(i):
        for nome, _, ini, fim in CAPITULOS:
            if ini <= i < fim:
                return nome
        return None

    # O cabeçalho que abre cada capítulo dá-lhe o título e não entra no corpo.
    INICIOS, TITULOS = set(), {}
    for p in doc.root.iter(q("p")):
        if doc.estilo(p) != "Heading2":
            continue
        i = doc.idx(p)
        nome = ficheiro_de(i)
        if nome and nome not in TITULOS:
            TITULOS[nome] = re.sub(r"^(\d+\.|Anexo \d+[.:]?)\s*", "",
                                   doc.texto_simples(p)).strip(" .:")
            INICIOS.add(i)

    for el in body:
        tag = el.tag.split("}")[-1]
        if tag == "p":
            i = doc.idx(el)
            nome = ficheiro_de(i)
            if nome is None:
                continue
            est = doc.estilo(el)
            if est.startswith("TOC"):
                continue
            texto = doc.inline(el)
            if not texto and not doc.imagens(el):
                continue

            for fr in el.iter(q("footnoteReference")):
                notas_usadas[nome].add(fr.get(q("id")))

            if est == "Heading2":
                t = re.sub(r"^\d+\.\s*", "", doc.texto_simples(el)).strip()
                # o título do capítulo vai no YAML; os restantes viram ##
                if i in INICIOS:
                    continue
                saida[nome].append(f"## {t}\n")
            elif est == "Heading3":
                t = doc.texto_simples(el)
                m = re.match(r"^(\d\.\d)\.?\s+(.*)$", t)
                if m:
                    saida[nome].append(f"## {m.group(2)} {{#{ancora(m.group(1))}}}\n")
                else:
                    saida[nome].append(f"## {t}\n")
            elif est == "Heading4":
                t = doc.texto_simples(el)
                m = re.match(r"^(\d\.\d\.\d):?\s+(.*)$", t)
                if m:
                    saida[nome].append(
                        f"### {m.group(1)} {m.group(2)} {{#{ancora(m.group(1))}}}\n")
                else:
                    saida[nome].append(f"### {t}\n")
            elif doc.imagens(el):
                if texto:        # a legenda vem no mesmo parágrafo da imagem
                    saida[nome].append(f"{texto}\n")
                saida[nome] += doc.figura_md(el)
            elif doc.lista(el):
                saida[nome].append(f"- {texto}")
            else:
                saida[nome].append(f"{texto}\n")

        elif tag == "tbl":
            ps = list(el.iter(q("p")))
            if not ps:
                continue
            i = doc.idx(ps[0])
            nome = ficheiro_de(i)
            if nome is None:
                continue
            for p in ps:
                for fr in p.iter(q("footnoteReference")):
                    notas_usadas[nome].add(fr.get(q("id")))
            cols = max(len(r.findall(q("tc"))) for r in el.findall(q("tr")))
            saida[nome] += caixa_md(doc, el) if cols == 1 else tabela_md(doc, el)

    termos = carregar_glossario()
    resumo = []
    for nome, titulo, ini, fim in CAPITULOS:
        linhas = saida[nome]
        # remissões e glossário
        linhas = [aplicar_remissoes(l, nome) for l in linhas]
        n_gloss = ligar_glossario(linhas, list(termos))
        # notas de rodapé no fim do capítulo
        notas = sorted(notas_usadas[nome], key=int)
        if notas:
            linhas.append("")
            for fid in notas:
                linhas.append(f"[^{fid}]: {doc.notas[fid]}")
            linhas.append("")
        titulo = titulo or TITULOS.get(nome, nome)
        cab = ["---", f'title: "{titulo}"', "---", ""]
        if nome.startswith("01"):
            cab.append(AVISO)
        texto = "\n".join(arejar(tabelar_tabulacoes(cab + linhas)))
        texto = re.sub(r"\n{3,}", "\n\n", texto).rstrip() + "\n"
        (DESTINO / nome).write_text(texto, encoding="utf-8", newline="\n")
        resumo.append((nome, len(texto.split()), n_gloss,
                       sum(1 for l in linhas if l.startswith("## ")),
                       sum(1 for l in linhas if l.startswith("### "))))

    print(f"Escritos em {DESTINO.relative_to(RAIZ)}/:")
    for nome, pal, ng, h2, h3 in resumo:
        print(f"  {nome:<28} {pal:>6} palavras  {h2:>2} secções  {h3:>2} subsecções  "
              f"{ng:>3} ligações ao glossário")
    print(f"  {doc.copiadas} imagem(ns) copiada(s) para {FIGURAS.name}/ ({doc.traduzidas} já traduzidas pelo pipeline)")
    if doc.faltas:
        print(f"  AVISO: {len(doc.faltas)} parágrafos sem tradução na zona traduzida: "
              f"{doc.faltas[:10]}")


if __name__ == "__main__":
    main()
