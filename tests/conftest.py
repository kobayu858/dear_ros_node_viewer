import pydot

# NetworkX が pydot 3.0 以降で AttributeError を起こす問題への暫定パッチ
if not hasattr(pydot, 'quote_id_if_necessary') and hasattr(pydot, 'quote_if_necessary'):
    pydot.quote_id_if_necessary = pydot.quote_if_necessary