"""
Extrai as entradas do glossário do PDF para `glossario.yml`.

O PDF é um documento de saída: hifenização, quebras de linha e cabeçalhos de
página entram no texto extraído. Este script limpa isso e valida o resultado,
em vez de confiar nele.

O ficheiro `glossario.yml` é a fonte de verdade a partir daqui: dele nascem a
página do glossário e, mais tarde, o ligador automático de termos. Por isso a
reextração **preserva** o que foi curado à mão em cada entrada — os campos
`ligar` e `variantes` — e só atualiza o texto vindo do PDF. Termos que
desapareçam do PDF são assinalados, não apagados em silêncio.

Uso:
    python scripts/extrair_glossario.py
"""

import re
import sys
import unicodedata
from pathlib import Path

import yaml
from pypdf import PdfReader

RAIZ = Path(__file__).resolve().parent.parent
PDF = next(
    (p for p in (RAIZ / "materiais_de_referencia").glob("*.pdf")
     if "Gloss" in unicodedata.normalize("NFC", p.name)),
    None,
)
SAIDA = RAIZ / "glossario.yml"

CABECALHO = re.compile(r"Documento Interno de Trabalho\s*|Página \d+ de \d+")

# Uma entrada é "Termo (English term): definição", com o termo a começar por
# maiúscula e a definição a correr até à entrada seguinte.
ENTRADA = re.compile(
    r"(?m)^\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\n:()]{1,60}?)\s*\(([^)]{1,130})\)\s*:\s*"
    r"(.+?)(?=\n\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\n:()]{1,60}?\s*\([^)]{1,130}\)\s*:|\Z)",
    re.S,
)

# Termos genéricos de mais para virarem hiperligação no corpo do livro.
# Ligá-los cobriria o texto de azul sem acrescentar informação.
NAO_LIGAR = {
    "unidade", "orçamento", "despesa", "receita", "resultado", "produto",
    "eficiência", "eficácia", "economia", "custo", "preço", "recursos",
    "alocação", "dotação", "saúde", "financiamento", "pagamento", "conta",
    "programa", "projecto", "projeto", "risco", "controlo", "auditoria",
    "relatório", "plano", "meta", "indicador", "cobertura", "equidade",
}


PALAVRA = re.compile(r"[A-Za-zÀ-ÿ]{2,}")

# Palavras que a extração parte e que reunir_palavras() não consegue juntar,
# por a forma inteira não ocorrer noutro ponto do documento.
CORRECOES = {
    "gere ncia": "gerencia",
    "orçament ários": "orçamentários",
}


def reunir_palavras(texto):
    """Junta palavras que a extração partiu ao meio ("reco lha" -> "recolha").

    O PDF insere espaços dentro de palavras. Só se junta um par quando a
    palavra resultante já ocorre no documento e pelo menos uma das metades
    não é, ela própria, uma palavra do documento — o que impede juntar pares
    legítimos como "de mais".
    """
    # hífen solto: "Formula -based", "Mantêm -se"
    texto = re.sub(r"(\w)\s+-(\w)", r"\1-\2", texto)

    vocab = {}
    for w in PALAVRA.findall(texto):
        vocab[w.lower()] = vocab.get(w.lower(), 0) + 1

    juntos = []

    def talvez(m):
        a, b = m.group(1), m.group(2)
        junto = (a + b).lower()
        if vocab.get(junto, 0) >= 1 and not (
            vocab.get(a.lower(), 0) >= 2 and vocab.get(b.lower(), 0) >= 2
        ):
            juntos.append(f"{a} {b} -> {a}{b}")
            return a + b
        return m.group(0)

    texto = re.sub(r"\b([A-Za-zÀ-ÿ]{2,})\s([a-zà-ÿ]{2,})\b", talvez, texto)
    return texto, juntos


def slug(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "g-" + re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def limpar(s):
    """Junta palavras partidas por hífen no fim da linha e normaliza espaços."""
    s = CABECALHO.sub(" ", s)
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)   # hifenização de fim de linha
    s = re.sub(r"\s*\n\s*", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    # o extractor insere espaço antes de pontuação e dentro de parênteses
    s = re.sub(r"\s+([,.;:)])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    # o glossário é dividido por letras A–Z; a letra da secção seguinte cola-se
    # ao fim da definição anterior na extração
    s = re.sub(r"\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]$", "", s.strip())
    return s.strip()


def candidato(termo):
    """Termo específico o suficiente para valer uma hiperligação."""
    t = termo.strip()
    if t.isupper() and 2 <= len(t) <= 8:
        return True                       # siglas: sempre específicas
    if t.lower() in NAO_LIGAR:
        return False
    return len(t.split()) >= 2            # termos compostos são específicos


def main():
    if PDF is None or not PDF.exists():
        sys.exit("glossário não encontrado em materiais_de_referencia/")

    bruto = "\n".join((p.extract_text() or "") for p in PdfReader(PDF).pages)
    texto = CABECALHO.sub(" ", bruto)
    texto, juntos = reunir_palavras(texto)
    for errado, certo in CORRECOES.items():
        texto = texto.replace(errado, certo)
    print(f"  {len(juntos)} palavras partidas pela extração foram reunidas")
    for j in juntos[:10]:
        print("     ", j)

    entradas, vistos, duplicados = [], {}, []
    for termo, ingles, definicao in ENTRADA.findall(texto):
        t, en, d = limpar(termo), limpar(ingles), limpar(definicao)
        if not t or not d:
            continue
        chave = slug(t)
        if chave in vistos:
            duplicados.append(t)
            continue
        vistos[chave] = True
        entradas.append({"id": chave, "termo": t, "ingles": en, "definicao": d,
                         "ligar": False, "variantes": []})

    entradas.sort(key=lambda e: unicodedata.normalize(
        "NFKD", e["termo"].lower()).encode("ascii", "ignore"))

    # --- preâmbulo: os parágrafos rotulados antes da primeira entrada -----
    preambulo = []
    inicio = texto[:ENTRADA.search(texto).start()] if ENTRADA.search(texto) else ""
    for rot in ("Objectivo", "Como Utilizar", "Distinções Essenciais",
                "Sobre Este Documento"):
        m = re.search(
            rot + r"\.\s*(.+?)(?=\s(?:Objectivo|Como Utilizar|"
            r"Distinções Essenciais|Sobre Este Documento)\.|\Z)",
            inicio, re.S)
        if m:
            preambulo.append({"rotulo": rot, "texto": limpar(m.group(1))})

    # --- preserva a curadoria já feita -----------------------------------
    antigo = {}
    if SAIDA.exists():
        prev = yaml.safe_load(SAIDA.read_text(encoding="utf-8")) or {}
        antigo = {e["id"]: e for e in prev.get("entradas", [])}
        for e in entradas:
            if e["id"] in antigo:
                e["ligar"] = antigo[e["id"]].get("ligar", e["ligar"])
                e["variantes"] = antigo[e["id"]].get("variantes", [])
        sumidos = [a for a in antigo if a not in vistos]
        if sumidos:
            print(f"  ATENÇÃO: {len(sumidos)} termos já não estão no PDF: "
                  + ", ".join(antigo[s]["termo"] for s in sumidos[:8]))

    # --- validação --------------------------------------------------------
    avisos = []
    for e in entradas:
        d = e["definicao"]
        if len(d.split()) < 4:
            avisos.append(f"definição muito curta: {e['termo']} — {d!r}")
        if not d.endswith((".", ":", ")")):
            avisos.append(f"definição talvez truncada: {e['termo']} — …{d[-45:]!r}")
        if re.search(r"[a-zà-ú]{2}-\s", d):
            avisos.append(f"hífen suspeito: {e['termo']}")
    if duplicados:
        avisos.append(f"{len(duplicados)} termos repetidos: {', '.join(duplicados[:5])}")

    SAIDA.write_text(
        "# Fonte de verdade do glossário. Gerado de materiais_de_referencia/\n"
        "# por scripts/extrair_glossario.py; 'ligar' e 'variantes' são curados\n"
        "# à mão e sobrevivem à reextração.\n"
        + yaml.dump({"fonte": PDF.name, "preambulo": preambulo,
                     "entradas": entradas},
                    allow_unicode=True, sort_keys=False, width=90),
        encoding="utf-8")

    # Sugestões de curadoria: termos específicos que já ocorrem nos capítulos.
    corpo = " ".join(q.read_text(encoding="utf-8") for q in RAIZ.glob("*.qmd")
                     if q.name != "glossario.qmd").lower()
    sugeridos = sorted(
        ((corpo.count(e["termo"].lower()), e["termo"]) for e in entradas
         if candidato(e["termo"])),
        reverse=True)
    n_lig = sum(1 for e in entradas if e["ligar"])
    print(f"Escrito: {SAIDA}")
    print(f"  {len(entradas)} entradas, {n_lig} marcadas como ligáveis")
    com_uso = [(n, t) for n, t in sugeridos if n]
    print(f"  candidatos a ligar que já ocorrem no livro: {len(com_uso)}")
    for n, t in com_uso[:15]:
        print(f"     {n:>3}x  {t}")
    print(f"  {len(avisos)} avisos de validação")
    for a in avisos[:15]:
        print("   ·", a)


if __name__ == "__main__":
    main()
