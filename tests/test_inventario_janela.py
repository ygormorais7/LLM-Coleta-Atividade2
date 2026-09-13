"""Candidatos de uma janela recuperada entram no inventário sem reamostrar."""

from src.raw.inventario import mesclar_candidatos

UFMG = "Universidade Federal de Minas Gerais"


def _existente(chave, estrato, cota, ordem):
    return {"chave_origem": chave, "ies": UFMG, "ano": 2021, "estrato": estrato,
            "cota_estrato": cota, "ordem_na_fila": ordem, "na_cota_inicial": True}


def test_novos_entram_no_fim_da_fila_com_cota_ampliada_e_sem_duplicar():
    existentes = [_existente("oai:a", "ufmg|2020-2024", 3, 0),
                  _existente("oai:b", "ufmg|2020-2024", 3, 1)]
    novos = [{"chave_origem": "oai:b", "ies": UFMG, "ano": 2021},   # já estava
             {"chave_origem": "oai:c", "ies": UFMG, "ano": 2022},
             {"chave_origem": "oai:d", "ies": UFMG, "ano": 2016}]   # estrato novo

    mesclado, adicionados = mesclar_candidatos(existentes, novos, ["ies", "ano_faixa"])
    por_chave = {m["chave_origem"]: m for m in mesclado}

    assert [a["chave_origem"] for a in adicionados] == ["oai:c", "oai:d"]
    assert len(mesclado) == 4
    assert (por_chave["oai:c"]["estrato"], por_chave["oai:c"]["ordem_na_fila"]) == ("ufmg|2020-2024", 2)
    assert {m["cota_estrato"] for m in mesclado if m["estrato"] == "ufmg|2020-2024"} == {4}
    assert (por_chave["oai:d"]["estrato"], por_chave["oai:d"]["cota_estrato"]) == ("ufmg|2015-2019", 1)


def test_inventario_original_nao_e_alterado_em_memoria():
    existentes = [_existente("oai:a", "ufmg|2020-2024", 3, 0)]
    mesclar_candidatos(existentes, [{"chave_origem": "oai:z", "ies": UFMG, "ano": 2023}], ["ies", "ano_faixa"])
    assert existentes[0]["cota_estrato"] == 3
