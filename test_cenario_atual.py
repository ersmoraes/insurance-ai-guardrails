"""
Módulo de Teste Unitário Dinâmico - Pytest
Executa a validação formal das regras críticas com base no cenário configurado na interface.
"""

import json
import os
from datetime import datetime
import pytest

from test_regras_criticas_sinistro_d0 import (
    avaliar_sinistro_auto_d0,
    DadosApoliceECondutor,
    SinaisIAEFontesExternas,
    StatusConsultaExterna,
    DecisaoRoteamentoD0,
    detetar_prompt_injection,
)

SCENARIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cenario_atual.json")


def carregar_cenario_atual():
    if not os.path.exists(SCENARIO_FILE):
        pytest.skip("Nenhum cenário atual gravado para validação dinâmica.")

    with open(SCENARIO_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    apolice_raw = data.get("apolice", {})
    sinais_raw = data.get("sinais", {})

    data_sinistro = datetime.strptime(
        apolice_raw.get("data_ocorrencia_sinistro", "2026-10-15"), "%Y-%m-%d"
    ).date()

    validade_cnh_str = apolice_raw.get("validade_cnh")
    validade_cnh = (
        datetime.strptime(validade_cnh_str, "%Y-%m-%d").date()
        if validade_cnh_str
        else None
    )

    apolice = DadosApoliceECondutor(
        premio_adimplente=bool(apolice_raw.get("premio_adimplente", True)),
        condutor_autorizado_apolice=bool(apolice_raw.get("condutor_autorizado_apolice", True)),
        perfil_compativel=bool(apolice_raw.get("perfil_compativel", True)),
        validade_cnh=validade_cnh,
        data_ocorrencia_sinistro=data_sinistro,
    )

    status_base_str = sinais_raw.get("status_base_restritiva", "SEM_RESTRICAO_CONFIRMADA")
    status_base = StatusConsultaExterna[status_base_str]

    sinais = SinaisIAEFontesExternas(
        relato_aviso=str(sinais_raw.get("relato_aviso", "")),
        score_ml_fraude=float(sinais_raw.get("score_ml_fraude", 0.08)),
        confianca_ocr_documentos=float(sinais_raw.get("confianca_ocr_documentos", 0.95)),
        status_base_restritiva=status_base,
        llm_sugeriu_aprovacao=bool(sinais_raw.get("llm_sugeriu_aprovacao", True)),
    )

    return apolice, sinais


def test_validacao_formal_cenario_atual():
    """
    Testa dinamicamente no Pytest o cenário que o usuário acabou de configurar na tela.
    Valida as asserções de negócio e governança determinística.
    """
    apolice, sinais = carregar_cenario_atual()

    resultado = avaliar_sinistro_auto_d0(apolice, sinais)

    # 1. Auditoria de Prompt Injection
    tem_injection = detetar_prompt_injection(sinais.relato_aviso)
    if tem_injection:
        assert resultado.decisao == DecisaoRoteamentoD0.FILA_SINDICANCIA_FRAUDE
        assert resultado.permite_stp_sem_humano is False
        assert any("Prompt Injection" in m for m in resultado.motivos_bloqueio_ou_alerta)
        print("\n[ASSERT PASS] Guardrail anti-injection interceptou tentativa maliciosa.")
        return

    # 2. Auditoria das Regras Inegociáveis
    regras_violadas = []
    if not apolice.premio_adimplente:
        regras_violadas.append("Prêmio em atraso")
    if not apolice.condutor_autorizado_apolice:
        regras_violadas.append("Condutor inválido")
    if not apolice.perfil_compativel:
        regras_violadas.append("Perfil divergente")
    if apolice.validade_cnh is None or apolice.validade_cnh < apolice.data_ocorrencia_sinistro:
        regras_violadas.append("CNH vencida ou ausente")

    if regras_violadas:
        assert resultado.decisao == DecisaoRoteamentoD0.BLOQUEIO_REGRA_INEGOCIAVEL
        assert resultado.permite_stp_sem_humano is False
        assert len(resultado.motivos_bloqueio_ou_alerta) >= 1
        print(f"\n[ASSERT PASS] Regra inegociável violada detectada: {regras_violadas}. Bloqueio determinístico mantido.")
        return

    # 3. Auditoria de Risco de Fraude / Sindicância
    if sinais.score_ml_fraude >= 0.75 or sinais.status_base_restritiva == StatusConsultaExterna.COM_RESTRICAO:
        assert resultado.decisao == DecisaoRoteamentoD0.FILA_SINDICANCIA_FRAUDE
        assert resultado.permite_stp_sem_humano is False
        print("\n[ASSERT PASS] Risco de fraude ou restrição externa confirmada. Roteado para Sindicância.")
        return

    # 4. Auditoria de Incerteza (Retorno vazio em API, OCR baixo ou Parecer LLM divergente)
    fatores_incerteza = []
    if sinais.status_base_restritiva == StatusConsultaExterna.RETORNO_VAZIO_OU_ERRO:
        fatores_incerteza.append("Retorno vazio em lista restritiva")
    if sinais.confianca_ocr_documentos < 0.85:
        fatores_incerteza.append("OCR abaixo do corte de 85%")
    if not sinais.llm_sugeriu_aprovacao:
        fatores_incerteza.append("Parecer divergente do LLM")

    if fatores_incerteza:
        assert resultado.decisao == DecisaoRoteamentoD0.FILA_ANALISTA_HUMANO
        assert resultado.permite_stp_sem_humano is False
        print(f"\n[ASSERT PASS] Incertezas identificadas: {fatores_incerteza}. Encaminhado para Analista Humano.")
        return

    # 5. Auditoria de Caso 100% Limpo (STP Aprovado)
    assert resultado.decisao == DecisaoRoteamentoD0.APROVACAO_AUTOMATICA_STP
    assert resultado.permite_stp_sem_humano is True
    assert resultado.motivos_bloqueio_ou_alerta == []
    print("\n[ASSERT PASS] Caso 100% regular e auditado. Elegível para Straight-Through Processing (STP).")
