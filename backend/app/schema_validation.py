"""Bounded offline JSON Schema validation shared by activities and HTTP contracts."""
import json
import threading
import time
from contextvars import ContextVar
from functools import lru_cache

_VALIDATION_BUDGET=ContextVar('mina_schema_validation_budget',default=None)
_VALIDATOR_LOCK=threading.Lock()


@lru_cache(maxsize=8)
def _cached_validator_type(base):
    # Cache only the bounded type for each standard draft. Never cache a schema,
    # input value, validator instance, or a caller's execution budget.
    import jsonschema, regex
    def pattern(validator, expression, instance, definition):
        if isinstance(instance, str):
            try: valid = regex.search(expression, instance, timeout=.1) is not None
            except (TimeoutError, regex.error): valid = False
            if not valid: yield jsonschema.ValidationError('String does not match the bounded schema pattern')
    def pattern_properties(validator, expressions, instance, definition):
        if not isinstance(instance,dict):return
        for expression,subschema in expressions.items():
            for name,item in instance.items():
                try:matched=regex.search(expression,name,timeout=.1) is not None
                except (TimeoutError,regex.error):raise ValueError('Invalid or over-budget schema property pattern') from None
                if matched:yield from validator.descend(item,subschema,path=name,schema_path=expression)
    def additional_properties(validator, additional, instance, definition):
        if not isinstance(instance,dict):return
        for name,item in instance.items():
            if name in definition.get('properties',{}):continue
            try:matched=any(regex.search(expression,name,timeout=.1) is not None for expression in definition.get('patternProperties',{}))
            except (TimeoutError,regex.error):raise ValueError('Invalid or over-budget schema property pattern') from None
            if matched:continue
            if additional is False:yield jsonschema.ValidationError('Additional property is not permitted: '+name)
            elif isinstance(additional,dict):yield from validator.descend(item,additional,path=name)
    def bounded(function):
        def check(*args):
            budget=_VALIDATION_BUDGET.get()
            budget[1]+=1
            if budget[1]>100000 or time.monotonic()-budget[0]>5:raise ValueError('API schema validation budget exceeded')
            yield from function(*args)
        return check
    checks={**base.VALIDATORS,'pattern':pattern,'patternProperties':pattern_properties,'additionalProperties':additional_properties}
    return jsonschema.validators.extend(base,{key:bounded(value) for key,value in checks.items()})


def _offline_schema(uri):
    from referencing.exceptions import NoSuchResource
    raise NoSuchResource(ref=uri)


def schema_errors(value, schema, registry=None):
    """Never retrieve schema URLs during validation; API refs are bundled first."""
    if isinstance(schema, str):
        try: schema = json.loads(schema)
        except ValueError:
            from .data_formats import DataFormats
            if not isinstance(value,(str,bytes,bytearray)):return ['XSD validation requires XML text or bytes']
            try:DataFormats.validate_xml_document(value,schema)
            except Exception as error:return [str(error)]
            return []
    if schema is None or schema == '': return []
    if isinstance(value,(bytes,bytearray)) and isinstance(schema,dict) and schema.get('type')=='string' and schema.get('format') in ('binary','byte'):
        import base64
        value=bytes(value).decode('latin1') if schema.get('format')=='binary' else base64.b64encode(value).decode()
    import jsonschema
    from referencing import Registry
    with _VALIDATOR_LOCK:
        validator_type=_cached_validator_type(jsonschema.validators.validator_for(schema))
    token=_VALIDATION_BUDGET.set([time.monotonic(),0])
    try:
        validator = validator_type(schema, registry=registry if registry is not None else Registry(retrieve=_offline_schema),format_checker=jsonschema.FormatChecker())
        errors=[]
        for error in validator.iter_errors(value):
            errors.append(f"{'.'.join(map(str,error.absolute_path)) or '$'}: {error.message}")
            if len(errors) >= 20: break
        return errors
    except Exception as error:
        raise ValueError('Invalid or unresolved API schema') from error

    finally:
        _VALIDATION_BUDGET.reset(token)
