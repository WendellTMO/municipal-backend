-- Relatório da telemetria de uso. Parâmetro: :dias (padrão 7, passado pelo relatorio-telemetria.sh).
\echo '== 1. Uso por dia e perfil (usuários e sessões distintos)'
SELECT date_trunc('day', ocorrido_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
       coalesce(papel, '?') AS perfil,
       count(DISTINCT usuario_id) AS usuarios,
       count(DISTINCT sessao_id) AS sessoes
FROM evento_telemetria
WHERE ocorrido_em > now() - (:dias || ' days')::interval
GROUP BY 1, 2 ORDER BY 1 DESC, 2;

\echo '== 2. Telas mais abertas (aberturas, tempo médio na tela em segundos, usuários)'
SELECT nome AS tela, count(*) AS aberturas,
       round(avg((props->>'dur_s')::numeric), 1) AS segundos_medios,
       count(DISTINCT usuario_id) AS usuarios
FROM evento_telemetria
WHERE tipo = 'tela' AND ocorrido_em > now() - (:dias || ' days')::interval
GROUP BY 1 ORDER BY 2 DESC LIMIT 20;

\echo '== 3. Ações mais usadas'
SELECT nome AS acao, count(*) AS vezes, count(DISTINCT usuario_id) AS usuarios
FROM evento_telemetria
WHERE tipo = 'acao' AND ocorrido_em > now() - (:dias || ' days')::interval
GROUP BY 1 ORDER BY 2 DESC LIMIT 25;

\echo '== 4. API: chamadas, erros e tempo por rota (média ponderada e pior caso, em ms)'
SELECT nome AS rota,
       sum((props->>'n')::int) AS chamadas,
       sum((props->>'erros')::int) AS erros,
       round(100.0 * sum((props->>'erros')::int) / nullif(sum((props->>'n')::int), 0), 1) AS pct_erro,
       round(sum((props->>'ms_medio')::numeric * (props->>'n')::int) / nullif(sum((props->>'n')::int), 0)) AS ms_medio,
       max((props->>'ms_max')::int) AS ms_pior
FROM evento_telemetria
WHERE tipo = 'api' AND ocorrido_em > now() - (:dias || ' days')::interval
GROUP BY 1 ORDER BY chamadas DESC LIMIT 25;

\echo '== 5. Envio de localização do motorista (por aparelho): tentativas, falhas e tempo'
SELECT coalesce(dispositivo, '?') AS aparelho, coalesce(versao_so, '?') AS sistema,
       sum((props->>'n')::int) AS envios,
       sum((props->>'erros')::int) AS falhas,
       round(sum((props->>'ms_medio')::numeric * (props->>'n')::int) / nullif(sum((props->>'n')::int), 0)) AS ms_medio
FROM evento_telemetria
WHERE tipo = 'api' AND nome LIKE 'post:/viagens/:id/localizacao'
  AND ocorrido_em > now() - (:dias || ' days')::interval
GROUP BY 1, 2 ORDER BY envios DESC LIMIT 15;

\echo '== 6. Erros do app (por nome, tela e mensagem)'
SELECT nome AS erro, coalesce(props->>'tela', '') AS tela, left(coalesce(props->>'msg', ''), 70) AS mensagem,
       count(*) AS vezes, count(DISTINCT usuario_id) AS usuarios
FROM evento_telemetria
WHERE tipo = 'erro' AND ocorrido_em > now() - (:dias || ' days')::interval
GROUP BY 1, 2, 3 ORDER BY vezes DESC LIMIT 15;

\echo '== 7. Problemas de localização do motorista (GPS e serviço)'
SELECT nome, coalesce(props->>'tipo', props->>'resultado', '') AS detalhe, count(*) AS vezes
FROM evento_telemetria
WHERE nome IN ('gps_erro', 'servico_localizacao', 'voltar_bloqueado', 'aviso_bateria_respondido')
  AND ocorrido_em > now() - (:dias || ' days')::interval
GROUP BY 1, 2 ORDER BY 3 DESC;

\echo '== 8. Versões do app e aparelhos'
SELECT coalesce(versao_app, '?') AS versao, plataforma, count(DISTINCT sessao_id) AS sessoes
FROM evento_telemetria
WHERE ocorrido_em > now() - (:dias || ' days')::interval
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 10;

SELECT coalesce(dispositivo, '?') AS aparelho, coalesce(versao_so, '?') AS sistema, count(DISTINCT sessao_id) AS sessoes
FROM evento_telemetria
WHERE ocorrido_em > now() - (:dias || ' days')::interval
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 12;

\echo '== 9. Onde mais se toca (por tela e célula da grade 6x10: cNrM = coluna N, linha M, 0 é canto superior esquerdo)'
SELECT nome AS tela, props->>'celula' AS celula, sum((props->>'n')::int) AS toques,
       count(DISTINCT usuario_id) AS usuarios
FROM evento_telemetria
WHERE tipo = 'toque' AND ocorrido_em > now() - (:dias || ' days')::interval
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 30;

\echo '== 10. Volume guardado'
SELECT count(*) AS eventos, min(recebido_em)::date AS mais_antigo, pg_size_pretty(pg_total_relation_size('evento_telemetria')) AS tamanho
FROM evento_telemetria;
