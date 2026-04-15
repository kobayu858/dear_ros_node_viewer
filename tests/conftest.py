import pydot

if not hasattr(pydot, 'quote_id_if_necessary') and hasattr(pydot, 'quote_if_necessary'):
    pydot.quote_id_if_necessary = pydot.quote_if_necessary

