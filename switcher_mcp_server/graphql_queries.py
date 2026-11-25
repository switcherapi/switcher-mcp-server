"""GraphQL query definitions for the Switcher admin GraphQL API."""

DOMAIN_FIELDS = """
    id: _id
    version
    name
    description
    activated
"""

GROUP_FIELDS = """
    _id
    name
    description
    activated
"""

CONFIG_FIELDS = """
    _id
    key
    description
    activated
    components
    relay {
        type
        method
        endpoint
        description
        activated
    }
"""

STRATEGY_FIELDS = """
    _id
    strategy
    description
    operation
    values
    activated
"""

CONFIGURATION_BY_KEY_QUERY = f"""
query ConfigurationByKey($domain: String!, $key: String, $environment: String) {{
    configuration(domain: $domain, key: $key, environment: $environment) {{
        domain {{{DOMAIN_FIELDS}}}
        group {{{GROUP_FIELDS}}}
        config {{{CONFIG_FIELDS}}}
        strategies {{{STRATEGY_FIELDS}}}
    }}
}}
"""
