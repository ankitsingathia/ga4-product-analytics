{#- Source/medium to a channel. '<Other>' and '(data deleted)' are the
    sample's obfuscation, kept as their own bucket rather than guessed at. -#}
{% macro channel_group(source, medium) -%}
case
    when {{ source }} is null and {{ medium }} is null then 'Unknown'
    when {{ source }} in ('<Other>', '(data deleted)')
      or {{ medium }} in ('<Other>', '(data deleted)') then 'Obfuscated'
    when {{ source }} = '(direct)' or {{ medium }} in ('(none)', '(not set)') then 'Direct'
    when {{ medium }} = 'organic' then 'Organic Search'
    when {{ medium }} in ('cpc', 'ppc', 'paid') then 'Paid Search'
    when {{ medium }} = 'referral' then 'Referral'
    when {{ medium }} = 'email' then 'Email'
    else 'Other'
end
{%- endmacro %}
