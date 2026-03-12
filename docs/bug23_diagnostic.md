# BUG-23 Diagnostic

## Definición operativa
- BUG-23 ocurre cuando el commit final mezcla idiomas/scripts, deriva semánticamente o publica texto no confiable para target `Spanish`.
- `hallucinated_commit_rate` aquí cuenta solo commits finales inseguros por pureza/deriva del texto final: `mixed_script`, `non_target_language`, `translation_too_similar_to_source` o `semantic_drift_score > 0.30`.

## Baseline actual
- commits: 14
- drops: 20
- mixed_script_rate: 0.0%
- non_spanish_commit_rate: 0.0%
- hallucinated_commit_rate: 0.0%
- one_word_commit_rate: 0.0%
- avg_source_confidence: 0.506
- avg_semantic_drift: 0.124
- top_root_cause: stt_or_merge

## Hotspots
- stt_or_merge: 14

## Causa raíz probable
- Predomina `stt_or_merge` en el fixture analizado.
- Si domina `stt_or_merge`, el drift nace antes de traducir: source fragmentado, mezclado o incompleto.
- Si domina `translation`, el source llega razonable pero la salida final rompe pureza de idioma o se parece demasiado al inglés.
- Si domina `commit_guard_gap`, el texto intermedio todavía no es seguro y el commit se publica demasiado pronto.

## Fixes propuestos
- reforzar `source_confidence` antes del commit final
- bloquear commits demasiado parecidos al source cuando target es español
- seguir trazando `source_text_raw -> source_text_sanitized -> translation_commit` por segmento

## Antes / Después
- baseline commits: 25
- current commits: 14
- baseline drops: 3
- current drops: 20
- baseline hallucinated_commit_rate: 0.0%
- current hallucinated_commit_rate: 0.0%
- baseline non_spanish_commit_rate: 0.0%
- current non_spanish_commit_rate: 0.0%
- baseline avg_source_confidence: 0.504
- current avg_source_confidence: 0.506
