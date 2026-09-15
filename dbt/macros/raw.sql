{#- The raw extract is Parquet on disk; the files are the source tables.
    GPA_RAW_DIR points at data/raw (BigQuery) or data/raw_synth (synthetic). -#}
{% macro raw(name) -%}
read_parquet('{{ env_var("GPA_RAW_DIR", "../data/raw_synth") }}/{{ name }}/*.parquet')
{%- endmacro %}
