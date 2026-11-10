"""Convert a supported BusinessWorks process graph into executable MINA activities."""
import re
from urllib.parse import urlsplit

from .mapper_xml import XSL, etree, parse_xml


BPEL = '{http://docs.oasis-open.org/wsbpel/2.0/process/executable}'
BW = '{http://www.tibco.com/bpel/2007/extensions}'
BW_ACTIVITY = '{http://tns.tibco.com/bw/model/core/bwext}BWActivity'
JNDI = '{http://xsd.tns.tibco.com/amf/models/sharedresource/jndi}'
XSI_TYPE = '{http://www.w3.org/2001/XMLSchema-instance}type'
XMI = '{http://www.omg.org/XMI}'
HTTP_CLIENT_NS = 'http://xsd.tns.tibco.com/bw/models/sharedresource/httpclient'
HTTP_SERVER_NS = 'http://xsd.tns.tibco.com/bw/models/sharedresource/httpconnector'
JDBC_NS = 'http://xsd.tns.tibco.com/amf/models/sharedresource/jdbc'
_PROCESS_METADATA = {'partnerLinks', 'variables', 'extensions', 'import'}
_NODE_METADATA = {'sources', 'targets', 'documentation'}
_LINK_TYPES = {'SUCCESS': 'success', 'SUCCESSWITHCONDITION': 'success_condition',
               'SUCCESSWITHNOCONDITION': 'success_no_match', 'ERROR': 'error'}
XML_JSON_FORMATS = {
    'bw.xml.parsexml': ('xml', 'parse'), 'bw.xml.renderxml': ('xml', 'render'),
    'bw.restjson.jsonparser': ('json', 'parse'), 'bw.restjson.jsonrender': ('json', 'render'),
}


def expanded_name(node, value):
    if not value: return ''
    if value.startswith('{'): return str(etree.QName(value))
    prefix, separator, name = value.partition(':')
    if not separator: return str(etree.QName(value))
    namespace = node.nsmap.get(prefix)
    if not namespace: raise ValueError(f'unknown schema prefix {prefix!r}')
    return str(etree.QName(namespace, name))


def _link_options(link, variables):
    kind = link['type']
    source = link['condition']
    if kind != 'success_condition':
        if source is not None:
            raise ValueError('unexpected XPath on BusinessWorks transition')
        return {'type': kind}
    if source is None:
        raise ValueError('conditional BusinessWorks transition requires executable XPath')
    expression = (source.text or '').strip()
    version = source.get('expressionLanguage', '').rsplit(':', 1)[-1].removeprefix('xpath') or '1.0'
    if not expression or len(expression) > 4096 or version not in {'1.0', '2.0'}:
        raise ValueError('unsupported BusinessWorks transition XPath')
    names = set(re.findall(r'\$([A-Za-z_][\w.-]*)', expression))
    if any(name in variables and variables[name] is None for name in names):
        raise ValueError('conditional link refers to a connector output requiring a BW XML shape adapter')
    return {'type': kind, 'condition': expression,
            'bw_xpath': {'version': version, 'variables': {name: variables.get(name, 'input.' + name).removeprefix('${').removesuffix('}') for name in sorted(names)},
                         'namespaces': {key: value for key, value in source.nsmap.items() if key}}}


def bindings(inputs):
    if inputs is None:
        return []
    result = list(inputs.iter(XSL + 'stylesheet', XSL + 'transform'))
    for candidate in inputs.iter():
        expression = (candidate.get('expression') or candidate.text or '').strip()
        if expression.startswith('<') and XSL[1:-1] in expression:
            parsed = parse_xml(expression)
            if parsed.tag in (XSL + 'stylesheet', XSL + 'transform'):
                result.append(parsed)
    return result


def mapper_config(binding, known_variables=None):
    if binding.get('version') not in ('1.0', '2.0'):
        raise ValueError('the binding requires an unsupported XSLT version')
    variables = {}
    for parameter in binding.findall(XSL + 'param'):
        name = parameter.get('name') or ''
        if not re.fullmatch(r'[A-Za-z_][\w.-]*', name):
            raise ValueError(f'unsupported XSLT parameter {name!r}')
        if known_variables is not None and name in known_variables and known_variables[name] is None:
            raise ValueError(f'connector output {name} requires a BW XML shape adapter')
        variables[name] = (known_variables or {}).get(name, '${input.' + name + '}')
    config = {'xmlStylesheet': etree.tostring(binding, encoding='unicode')}
    if variables:
        config.update(xmlVariables=variables, xmlSource='<input/>')
    return config


def _settings(node, allowed):
    if node is None:
        return {}
    values = {}
    for field in node:
        key = etree.QName(field).localname
        if key not in allowed or key in values or field.attrib or len(field):
            raise ValueError(f'unsupported or nonliteral setting {key}')
        values[key] = (field.text or '').strip()
    if node.attrib:
        raise ValueError(f'unsupported attributes on {etree.QName(node).localname}')
    return values


def jdbc_resource(document, name, resource_id):
    settings = document.find(JNDI + 'configuration')
    if document.tag != JNDI + 'namedResource' or settings is None:
        raise ValueError('expected a BW JDBC named resource')
    prefix, _, kind = settings.get(XSI_TYPE, '').partition(':')
    connection = settings.find('connectionConfig')
    if settings.nsmap.get(prefix) != JDBC_NS or kind != 'JdbcDataSource' or connection is None:
        raise ValueError('expected a BW JDBC data source')
    prefix, _, kind = connection.get(XSI_TYPE, '').partition(':')
    if connection.nsmap.get(prefix) != JDBC_NS or kind != 'NonXaConnection':
        raise ValueError('XA JDBC resources require review')
    if any(reference.get('value') for reference in document.findall(JNDI + 'reference')):
        raise ValueError('JDBC identity and subject resources require review')
    if (set(settings.attrib) - {XSI_TYPE, XMI + 'id', 'username', 'password'}
            or set(connection.attrib) - {XSI_TYPE, XMI + 'id', 'jdbcDriver', 'dbURL', 'loginTimeout'}
            or len(settings) != 1):
        raise ValueError('unsupported JDBC connection or pooling policy')
    drivers = {'org.sqlite.JDBC': 'sqlite', 'org.postgresql.Driver': 'postgresql',
               'com.mysql.cj.jdbc.Driver': 'mysql', 'com.mysql.jdbc.Driver': 'mysql',
               'oracle.jdbc.OracleDriver': 'oracle', 'oracle.jdbc.driver.OracleDriver': 'oracle',
               'com.microsoft.sqlserver.jdbc.SQLServerDriver': 'sqlserver'}
    driver_class = connection.get('jdbcDriver', '')
    driver = drivers.get(driver_class)
    if not driver:
        raise ValueError('unsupported JDBC driver class')
    url = connection.get('dbURL', '')
    properties = []
    substitutions = list(connection)
    if substitutions:
        binding = substitutions[0]
        key = binding.get('propName', '')
        if (len(substitutions) != 1 or binding.tag != 'substitutionBindings' or binding.get('template') != 'dbURL'
                or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', key)):
            raise ValueError('unsupported JDBC property substitution')
        url = url.removeprefix(key).strip()
        properties.append({'key': key, 'value': url, 'data_type': 'string'})
    if not url.startswith('jdbc:') or re.search(r'(?i)(?:password|pwd|user)\s*=|://[^/]*@', url):
        raise ValueError('JDBC URL requires a portable default without embedded credentials')
    config = {'driver': driver, 'driverClass': driver_class, 'url': url, 'username': settings.get('username', '')}
    if properties:
        config['url'] = '${properties.' + properties[0]['key'] + '}'
    if settings.get('password'):
        key = f'{resource_id}.password'
        properties.append({'key': key, 'value': '', 'data_type': 'password'})
        config['password'] = '${properties.' + key + '}'
    if connection.get('loginTimeout'):
        config['timeoutSeconds'] = int(connection.get('loginTimeout'))
    return {'id': resource_id, 'type': 'jdbc', 'name': document.get('name') or name, 'config': config}, properties


def jms_resource(document, name, resource_id):
    fields = {'serverUrl', 'username', 'password', 'clientId', 'connectionFactoryClass', 'connectionFactory',
              'connectionFactoryType', 'jndiContextFactory', 'jndiProviderUrl', 'jndiUsername', 'jndiPassword',
              'connectionTimeoutSeconds', 'mode'}
    if document.tag == JNDI + 'namedResource':
        node = document.find(JNDI + 'configuration')
        if node is None or len(document) != 1 or len(node) or set(node.attrib) - fields - {XSI_TYPE, XMI + 'id'}:
            raise ValueError('unsupported JMS resource configuration or external policy')
        if node.get(XSI_TYPE, '').split(':')[-1] not in {'JMSConnection', 'JMSConnectionConfiguration', 'JmsConnectionConfiguration'}:
            raise ValueError('expected a BW JMS connection')
        config = {key: node.get(key) for key in fields if key in node.attrib}
    elif etree.QName(document).localname in {'JMSConnection', 'JmsConnection'}:
        config = _settings(document, fields)
    else:
        raise ValueError('expected a BW JMS connection')
    mode = config.get('connectionFactoryType', 'JNDI' if config.get('jndiProviderUrl') else 'Direct')
    if mode.lower() not in {'direct', 'jndi'}:
        raise ValueError('unsupported JMS connection factory type')
    config['connectionFactoryType'] = 'JNDI' if mode.lower() == 'jndi' else 'Direct'
    if config.get('mode') not in (None, 'memory'):
        raise ValueError('unsupported JMS transport mode')
    if config.get('mode') != 'memory' and not (
            all(config.get(key) for key in ('jndiProviderUrl', 'jndiContextFactory', 'connectionFactory'))
            if mode.lower() == 'jndi' else config.get('serverUrl')):
        raise ValueError('JMS provider and connection factory settings are required')
    for key in ('serverUrl', 'jndiProviderUrl'):
        if re.search(r'(?i)://[^/]*@|password\s*=', config.get(key, '')):
            raise ValueError('JMS provider URLs cannot contain embedded credentials')
    properties = []
    for key in ('password', 'jndiPassword'):
        if config.get(key):
            prop = f'{resource_id}.{key}'
            properties.append({'key': prop, 'value': '', 'data_type': 'password'})
            config[key] = '${properties.' + prop + '}'
    return {'id': resource_id, 'type': 'jms', 'name': document.get('name') or name, 'config': config}, properties


def http_resource(document, name, resource_id):
    integer_options = {'connectionTimeout': 'connectionTimeoutMs', 'socketTimeout': 'socketTimeoutMs',
                       'maxTotalConnections': 'maximumTotalConnections', 'maxConnectionsPerHost': 'maximumConnectionsPerHost',
                       'idleConnectionTimeout': 'idleConnectionTimeoutMs', 'proxyPort': 'proxyPort'}
    boolean_options = {'usePersistentConnections', 'disableConnectionPooling', 'enableCookies', 'defaultConfidentiality'}
    text_options = {'host', 'port', 'scheme', 'proxyHost', 'httpVersion', 'tlsVersion', 'maximumTlsVersion',
                    'certificateAuthorityFile'}
    allowed = set(integer_options) | boolean_options | text_options
    if document.tag == JNDI + 'namedResource':
        configuration = document.find(JNDI + 'configuration')
        if configuration is None or len(document) != 1:
            raise ValueError('expected one HTTP client configuration')
        prefix, _, type_name = configuration.get(XSI_TYPE, '').partition(':')
        if configuration.nsmap.get(prefix) != HTTP_CLIENT_NS or type_name != 'HttpClientConfiguration':
            raise ValueError('expected a BusinessWorks HTTP client shared resource')
        tcp = configuration.find('tcpDetails')
        if (tcp is None or len(configuration) != 1 or len(tcp)
                or set(configuration.attrib) - {XSI_TYPE, XMI + 'id', 'httpClientVersion'} - allowed
                or set(tcp.attrib) - {XMI + 'id'} - allowed):
            raise ValueError('HTTP substitution bindings, TLS settings, or advanced transport policies require review')
        settings = {key: value for node in (configuration, tcp) for key, value in node.attrib.items() if key in allowed}
        name = document.get('name') or name
    elif etree.QName(document).localname in {'HTTPClient', 'HttpClient', 'httpClient', 'httpClientResource'}:
        settings = _settings(document, allowed)
    else:
        raise ValueError('unsupported HTTP shared resource format')
    scheme, host = settings.get('scheme', 'http').lower(), settings.get('host', '')
    if scheme not in {'http', 'https'} or not re.fullmatch(r'[A-Za-z0-9.-]+', host):
        raise ValueError('HTTP client requires a literal host and http or https scheme')
    port = int(settings.get('port', 443 if scheme == 'https' else 80))
    if not 1 <= port <= 65535:
        raise ValueError('HTTP client port is outside 1–65535')
    config = {'connectorMode': 'client', 'baseUrl': f'{scheme}://{host}:{port}'}
    for source, target in integer_options.items():
        if source in settings:
            milliseconds = int(settings[source])
            if milliseconds <= 0:
                raise ValueError(f'{source} must be positive')
            config[target] = milliseconds
    for key in boolean_options & settings.keys():
        if settings[key].lower() not in {'true', 'false'}:
            raise ValueError(f'invalid HTTP boolean setting {key}')
        config[key] = settings[key].lower() == 'true'
    for key in text_options & settings.keys() - {'host', 'port', 'scheme'}:
        config[key] = settings[key]
    if config.get('defaultConfidentiality') and scheme != 'https':
        raise ValueError('HTTP default confidentiality requires an HTTPS endpoint')
    return {'id': resource_id, 'type': 'http', 'name': name, 'config': config}


def http_server_resource(document, name, resource_id):
    configuration = document.find(JNDI + 'configuration')
    if document.tag != JNDI + 'namedResource' or configuration is None or len(document) != 1:
        raise ValueError('expected a BW HTTP server named resource')
    prefix, _, kind = configuration.get(XSI_TYPE, '').partition(':')
    if configuration.nsmap.get(prefix) != HTTP_SERVER_NS or kind != 'HttpConnectorConfiguration':
        raise ValueError('expected a BW HTTP server connector')
    mapping = {'host': 'host', 'port': 'port', 'minThreads': 'minimumQtpThreads', 'maxThreads': 'maximumQtpThreads',
               'idleTimeout': 'idleConnectionTimeoutMs', 'maxHeaderSize': 'maxHeaderBytes'}
    if set(configuration.attrib) - set(mapping) - {XSI_TYPE, XMI + 'id'}:
        raise ValueError('unsupported HTTP server transport settings')
    config = {'connectorMode': 'server', 'host': configuration.get('host', '127.0.0.1'),
              'port': int(configuration.get('port', '8080'))}
    for source, destination in mapping.items():
        if source not in {'host', 'port'} and source in configuration.attrib:
            config[destination] = int(configuration.get(source))
    properties = []
    for binding in configuration:
        field, key = binding.get('template'), binding.get('propName', '')
        if (binding.tag != 'substitutionBindings' or field not in {'host', 'port'}
                or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', key)
                or any(item['key'] == key for item in properties) or len(binding)):
            raise ValueError('unsupported HTTP server property binding')
        properties.append({'key': key, 'value': config[field], 'data_type': 'integer' if field == 'port' else 'string'})
        config[field] = '${properties.' + key + '}'
    return {'id': resource_id, 'type': 'http', 'name': document.get('name') or name, 'config': config}, properties


def _binding_fields(binding):
    if binding is None:
        raise ValueError('expected an XSLT input binding')
    templates = binding.findall(XSL + 'template')
    if len(templates) != 1 or templates[0].get('match') != '/' or len(templates[0]) != 1:
        raise ValueError('expected one bound input wrapper')
    wrapper = templates[0][0]
    if wrapper.tag.startswith(XSL):
        raise ValueError('the bound input wrapper must have a fixed name')
    fields = {etree.QName(child).localname for child in wrapper}
    if len(fields) != len(wrapper):
        raise ValueError('duplicate bound input field names require review')
    return etree.QName(wrapper).localname, fields


class ProcessConverter:
    def __init__(self, document, task_id, name, resolve_task, resolve_resource, resolve_schema=None):
        self.document = document
        self.task_id = task_id
        self.name = name
        self.resolve_task = resolve_task
        self.resolve_resource = resolve_resource
        self.resolve_schema = resolve_schema or (lambda name: None)
        self.activities = []
        self.transitions = []
        self.variables = {}
        self.dependencies = set()
        self.resources = set()
        self.diagnostics = []
        self.link_endpoints = set()
        self.starter = False

    def node(self, kind, name, config=None):
        activity_id = f'bw-step-{len(self.activities)}'
        self.activities.append({'id': activity_id, 'name': name, 'type': kind, 'config': config or {},
                                'position': {'x': 70 + 175 * (len(self.activities) % 8),
                                             'y': 100 + 115 * (len(self.activities) // 8)}})
        return activity_id

    def connect(self, previous, next_id):
        for source in previous:
            self.transitions.append({'id': f'bw-link-{len(self.transitions)}', 'source': source, 'target': next_id})
        return [next_id]

    def convert(self):
        if self.document.tag != BPEL + 'process':
            raise ValueError('the source is not an executable BPEL 2.0 process')
        body = [node for node in self.document if node.tag.startswith(BPEL) and
                etree.QName(node).localname not in _PROCESS_METADATA]
        if len(body) != 1:
            raise ValueError('expected one executable process body')
        last = self.step(body[0], [self.node('start', 'Start')])
        if any(endpoint not in self.link_endpoints for endpoint in body[0].iter(BPEL + 'source', BPEL + 'target')):
            raise ValueError('nested or cross-scope process links require review')
        if self.activities[0]['type'] == 'http_listener':
            if not last or any(next(item for item in self.activities if item['id'] == activity)['type'] != 'http_response' for activity in last):
                raise ValueError('HTTP listener requires a single supported response binding')
        else:
            self.connect(last, self.node('end', 'End'))
        return {'id': self.task_id, 'name': self.name, 'kind': 'starter' if self.starter else 'subtask',
                'description': 'Converted BusinessWorks process. Check its input XML and connection settings before deployment.',
                'activities': self.activities, 'transitions': self.transitions}

    def linked_flow(self, node, previous):
        links = node.find(BPEL + 'links')
        declared = {}
        if links is not None:
            for link in links:
                name = link.get('name')
                kind = _LINK_TYPES.get(link.get(BW + 'linkType', 'SUCCESS'))
                if link.tag != BPEL + 'link' or not name or name in declared or len(link) or not kind:
                    raise ValueError('unsupported BusinessWorks link declaration')
                declared[name] = {'type': kind, 'condition': None}
        members = [child for child in node if child is not links]
        for index, child in enumerate(members):
            endpoint = self.owner(child)
            for group, endpoint_name in (('sources', 'source'), ('targets', 'target')):
                for location in (child, endpoint) if endpoint is not child else (child,):
                    for item in location.findall(f'{BPEL}{group}/{BPEL}{endpoint_name}'):
                        match = declared.get(item.get('linkName'))
                        if match is None or endpoint_name in match:
                            raise ValueError('unsupported cross-scope process link')
                        allowed = {BPEL + 'transitionCondition', BW + 'DesignExpression'} if endpoint_name == 'source' else set()
                        if any(child.tag not in allowed for child in item):
                            raise ValueError('unsupported BusinessWorks link metadata')
                        if endpoint_name == 'source':
                            match['condition'] = item.find(BPEL + 'transitionCondition')
                        self.link_endpoints.add(item)
                        match[endpoint_name] = index
                    for container in location.findall(BPEL + group):
                        if any(item.tag != BPEL + endpoint_name for item in container):
                            raise ValueError('explicit BPEL link and join conditions require review')
        parents = {index: [] for index in range(len(members))}
        has_children = set()
        for link in declared.values():
            if 'source' not in link or 'target' not in link:
                raise ValueError('incomplete BPEL process link')
            parents[link['target']].append(link)
            has_children.add(link['source'])
        results, pending = {}, set(parents)
        original_variables = dict(self.variables)
        if len(members) - len(has_children) > 1:
            raise ValueError('parallel branches require an explicit common join')
        while pending:
            ready = sorted(index for index in pending if all(link['source'] in results for link in parents[index]))
            if not ready:
                raise ValueError('cyclic BPEL process links require review')
            for index in ready:
                incoming = {activity: _link_options(link, results[link['source']][1])
                            for link in parents[index] for activity in results[link['source']][0]}
                if len(incoming) != sum(len(results[link['source']][0]) for link in parents[index]):
                    raise ValueError('duplicate links between two activities require review')
                self.variables = dict(original_variables)
                incoming_variables = {}
                for link in parents[index]:
                    for key, value in results[link['source']][1].items():
                        if key in incoming_variables and incoming_variables[key] != value:
                            raise ValueError(f'parallel branches redefine variable {key}')
                        incoming_variables[key] = value
                self.variables.update(incoming_variables)
                first_edge = len(self.transitions)
                results[index] = (self.step(members[index], list(incoming) or previous), dict(self.variables))
                for activity, options in incoming.items():
                    edges = [edge for edge in self.transitions[first_edge:] if edge['source'] == activity]
                    if len(edges) != 1 and options['type'] != 'success':
                        raise ValueError('conditional link target must have a single entry')
                    for edge in edges:
                        edge.update(options)
                pending.remove(index)
        sinks = [index for index in results if index not in has_children]
        return results[sinks[0]][0] if sinks else previous

    @staticmethod
    def owner(node):
        if node.tag == BPEL + 'extensionActivity':
            extensions = [child for child in node if child.tag in {BW + 'extActivity', BW + 'activityExtension', BW + 'receiveEvent'}]
            if len(extensions) != 1:
                raise ValueError('expected one TIBCO extension activity')
            return extensions[0]
        return node

    def connection(self, name, kind):
        variable = next((item for item in self.document.findall(f'{BPEL}variables/{BPEL}variable')
                         if item.get('name') == name), None)
        literal = variable.findtext(f'{BPEL}from/{BPEL}literal') if variable is not None else None
        resource = self.resolve_resource(literal or name, kind)
        self.resources.add(resource)
        return resource

    def jms_config(self, value, operation):
        allowed = {XSI_TYPE, 'sharedResourceProperty', 'destination', 'destinationType', 'acknowledgeMode',
                   'selector', 'timeout', 'messageType'}
        if set(value.attrib) - allowed or len(value) or not value.get('destination'):
            raise ValueError('unsupported JMS activity options or missing destination')
        if value.get('messageType', 'Text').lower() != 'text':
            raise ValueError('only JMS TextMessage bindings can be converted')
        destination_type = value.get('destinationType', 'queue').lower()
        if destination_type not in {'queue', 'topic'}:
            raise ValueError('unsupported JMS destination type')
        acknowledgement = value.get('acknowledgeMode', 'Auto').lower()
        if acknowledgement not in {'auto', 'client'}:
            raise ValueError('unsupported JMS acknowledgement mode')
        config = {'operation': operation, 'destination': value.get('destination'),
                  'messagingStyle': destination_type.title(), 'acknowledgeMode': acknowledgement.title(),
                  'resourceId': self.connection(value.get('sharedResourceProperty'), 'jms')}
        if value.get('selector'):
            config['messageSelector'] = value.get('selector')
        if value.get('timeout'):
            config['receiveTimeout'] = int(value.get('timeout'))
        return config

    def event(self, owner, previous, label):
        source = owner.find(BW + 'eventSource')
        if (source is None or len(source) != 1 or previous != [self.activities[0]['id']]
                or self.activities[0]['type'] != 'start' or self.transitions or not owner.get('variable')):
            raise ValueError(f'{label}: expected one process entry event')
        event = source[0]
        variable = owner.get('variable')
        if event.tag == BW + 'StartEvent':
            self.variables[variable] = '${input}'
            return self.connect(previous, self.node('basic', label, {'operation': 'empty'}))
        if event.tag in {BW + 'JMSReceiveMessage', BW + 'JMSReceiveMessageEvent'}:
            config = self.jms_config(event, 'receive_message')
            kind, output = 'jms', 'body'
        elif event.tag == BW_ACTIVITY and event.get('activityTypeID', '').lower() == 'bw.generalactivities.timer':
            value = event.find("activityConfig/properties[@name='config']/value")
            if value is None: raise ValueError(f'{label}: missing BW timer configuration')
            cron, date = value.get('cronExpression'), value.get('startTime')
            if not cron and (value.get('runOnce', '').lower() != 'true' or not date):
                raise ValueError(f'{label}: repeating BW timers require review')
            config = {'operation': 'schedule', 'runOnceOnLocalStart': False,
                      'scheduleMode': 'cron' if cron else 'dateTime'}
            config['cronExpression' if cron else 'scheduledDateTime'] = cron or date
            kind, output = 'timer', ''
        elif event.tag == BW + 'TimerEvent':
            settings = _settings(event, {'cronExpression', 'scheduledDateTime'})
            if bool(settings.get('cronExpression')) == bool(settings.get('scheduledDateTime')):
                raise ValueError(f'{label}: expected a single timer schedule')
            config = {**settings, 'operation': 'schedule', 'runOnceOnLocalStart': False,
                      'scheduleMode': 'cron' if settings.get('cronExpression') else 'dateTime'}
            kind, output = 'timer', ''
        elif event.tag in {BW + 'HTTPReceiveEvent', BW + 'HTTPListenerEvent'}:
            settings = _settings(event, {'httpConnection', 'path', 'method', 'contentType'})
            path = settings.get('path', '')
            method = settings.get('method', 'POST').upper()
            if not re.fullmatch(r'/[A-Za-z0-9/_-]*', path) or method not in {'GET', 'POST', 'PUT', 'DELETE', 'PATCH'}:
                raise ValueError(f'{label}: unsupported HTTP event path or method')
            config = {'operation': 'listen', 'resourceId': self.connection(settings.get('httpConnection'), 'http:server'),
                      'path': path, 'method': method,
                      'requestContentTypes': [settings.get('contentType', 'application/xml')]}
            kind, output = 'http_listener', 'body'
        else:
            raise ValueError(f'{label}: unsupported external event binding {etree.QName(event).localname}')
        self.starter = True
        self.activities[0].update(type=kind, name=label, config=config)
        self.variables[variable] = '${activities.' + previous[0] + '.output.' + output + '}' if output else None
        return previous

    def step(self, node, previous):
        owner = self.owner(node)
        label = owner.get('name') or etree.QName(owner).localname
        if node.tag == BPEL + 'sequence':
            for child in node:
                if not (child.tag.startswith(BPEL) and etree.QName(child).localname in _NODE_METADATA):
                    previous = self.step(child, previous)
            return previous
        if node.tag == BPEL + 'scope':
            children = [child for child in node if etree.QName(child).localname not in _NODE_METADATA]
            if len(children) != 1 or set(node.attrib) - {'name', BW + 'xpdlId'}:
                raise ValueError(f'{label}: scope variables, handlers, or isolation require review')
            return self.step(children[0], previous)
        if node.tag == BPEL + 'flow':
            return self.linked_flow(node, previous)
        if owner.tag == BPEL + 'empty':
            if owner.get(BW + 'constructor'):
                raise ValueError(f'{label}: event boundary requires a native starter or response')
            return self.connect(previous, self.node('basic', label, {'operation': 'empty'}))
        if owner.tag == BW + 'receiveEvent':
            return self.event(owner, previous, label)
        if owner.tag == BPEL + 'reply' and self.activities[0]['type'] == 'http_listener':
            sheets = bindings(owner.find(BW + 'inputBindings'))
            if len(sheets) != 1 or owner.get('faultName'):
                raise ValueError(f'{label}: expected one successful XML reply binding')
            config = mapper_config(sheets[0], self.variables)
            config['bwXmlElementVariables'] = True
            mapped = self.node('mapper', label + '-Binding', config)
            after = self.connect(previous, mapped)
            return self.connect(after, self.node('http_response', label, {'operation': 'response',
                                'contentType': 'application/xml', 'body': '${activities.' + mapped + '.output.xmlString}'}))
        if owner.tag not in {BW + 'extActivity', BW + 'activityExtension'}:
            raise ValueError(f'{label}: unsupported BPEL activity {etree.QName(owner).localname}')
        design = owner.find(f'{BW}config/{BW_ACTIVITY}')
        kind = ((design.get('activityTypeID') if design is not None else owner.get('type')) or '').lower()
        value = design.find("activityConfig/properties[@name='config']/value") if design is not None else None
        sheets = bindings(owner.find(BW + 'inputBindings'))
        if len(sheets) > 1 or not sheets and owner.find(BW + 'inputBindings') is not None:
            raise ValueError(f'{label}: expected a single stylesheet input binding')
        binding = sheets[0] if sheets else None
        output_variable = owner.get('outputVariable') or label

        def map_binding():
            config = mapper_config(binding, self.variables)
            if owner.tag == BW + 'activityExtension':
                config['bwXmlElementVariables'] = True
                config.setdefault('xmlSource', '<input/>')
            return self.node('mapper', label + '-Binding', config)

        if kind in {'bw.generalactivities.mapper', 'bw.generalactivities.map'} and binding is not None:
            activity = map_binding()
            self.activities[-1]['name'] = label
            if value is not None and value.get('inputQName'):
                name = expanded_name(value, value.get('inputQName'))
                schema = self.resolve_schema(name)
                if schema:
                    # BW Mapper has no Parse/Render validation switch. Attach
                    # its design contract without adding runtime validation.
                    self.activities[-1]['config'].update(targetSchemaId=schema, validateOutput=False)
            self.variables[output_variable] = '${activities.' + activity + '.output.xmlString}'
        elif kind == 'bw.internal.end' and binding is not None:
            activity = map_binding()
            self.activities[-1]['name'] = label
            self.variables[output_variable] = '${activities.' + activity + '.output.xmlString}'
        elif kind in XML_JSON_FORMATS:
            family, operation = XML_JSON_FORMATS[kind]
            parsing = operation == 'parse'
            if value is None: raise ValueError(f'{label}: missing BW format configuration')
            config = {'operation': operation}
            flag = 'validateOutput' if parsing else 'validateInput'
            if family == 'xml':
                style_key = 'inputStyle' if parsing else 'outputStyle'
                style = (value.get(style_key) or 'text').lower()
                if style not in ({'text','binary','dynamic'} if parsing else {'text','binary'}):
                    raise ValueError(f'{label}: unsupported XML style {style!r}')
                config[style_key] = style.title()
                config[flag] = value.get(flag, 'false').lower() == 'true'
                qname = value.get('outputElementQName' if parsing else 'inputElementQName')
                if not parsing:
                    config.update(
                        suppressXmlDeclaration=value.get('suppressXMLDeclaration','false').lower() == 'true',
                        prettyPrint=value.get('disablePrettyPrint','false').lower() != 'true',
                        formatUsingDefaultNamespacePrefix=value.get('formatUsingDefaultNSPrefix','false').lower() == 'true',
                    )
                    if value.get('encoding'): config['encoding'] = value.get('encoding')
                    if value.get('cdata') or any(etree.QName(child).localname == 'cdata' for child in value):
                        raise ValueError(f'{label}: select the imported CDATA paths in MINA Input')
            else:
                mode = (value.get('schemaType') or 'xsd').lower()
                if mode not in ('generic','xsd'): raise ValueError(f'{label}: unsupported JSON schema type {mode!r}')
                config['schemaType'] = 'Generic' if mode == 'generic' else 'XSD'
                config[flag] = value.get(flag,'true' if parsing else 'false').lower() == 'true'
                style = (value.get('jsonInputStyle' if parsing else 'jsonOutputStyle') or '').lower()
                style = re.sub(r'[^a-z]', '', style)
                if style not in ('', 'none', 'jsonwithroot', 'withroot', 'anonymousarray', 'anonymous'):
                    raise ValueError(f'{label}: unsupported JSON root style {style!r}')
                config['jsonStyle'] = ('Anonymous Array' if style.startswith('anonymous') else
                                       'JSON with Root' if style.endswith('withroot') or (not parsing and not style and value.get('removeRoot') == 'false') else 'None')
                for source_key, target_key in (
                    ('bagerfish','badgerfish'), ('nullForEmpty','useNullForEmptyValues'),
                    ('IgnoreAdditionalJSONFields','ignoreAdditionalJsonFields'), ('emptyForNull','useEmptyValuesForNull'),
                    ('prettyPrint','prettyPrint'),
                ):
                    if source_key in value.attrib: config[target_key] = value.get(source_key).lower() == 'true'
                qname = value.get('outputElementQName') if mode == 'xsd' else None
            if qname:
                name = expanded_name(value, qname)
                schema = self.resolve_schema(name)
                if schema:
                    config.update(schemaId=schema, rootElement=name)
            if not config.get('schemaId') and ((family == 'xml' and config[flag]) or config.get('schemaType') == 'XSD'):
                raise ValueError(f'{label}: selected schema {qname or "(missing)"} is not in the imported project')
            if binding is not None:
                mapped = map_binding()
                previous = self.connect(previous, mapped)
                prefix = '${activities.' + mapped + '.output.'
                input_mappings = config.setdefault('inputMappings', {})
                if parsing:
                    expected = {'xmlString','xmlBinary'} if family == 'xml' else {'jsonString'}
                    root, fields = _binding_fields(binding)
                    if root in expected:
                        input_mappings[root] = prefix + ('value}' if root != 'xmlBinary' else root + '}')
                    elif fields and fields <= expected:
                        for field in fields: input_mappings[field] = prefix + root + '.' + field + '}'
                    else:
                        raise ValueError(f'{label}: unsupported Parse {family.upper()} input binding')
                else:
                    input_mappings['xmlString'] = prefix + 'xmlString}'
            if not parsing: config['bwOutputEnvelope'] = True
            activity = self.node(family, label, config)
            self.variables[output_variable] = '${activities.' + activity + '.output.' + ('xmlString' if parsing else 'bwXml') + '}'
        elif kind == 'bw.generalactivities.callprocess':
            call = owner.find(BW + 'CallProcess')
            if binding is not None or call is None or set(call.attrib) != {'subProcessName'} or len(call):
                raise ValueError(f'{label}: dynamic or bound Call Process requires review')
            target = self.resolve_task(call.get('subProcessName'))
            self.dependencies.add(target)
            activity = self.node('call_task', label, {'taskId': target})
            self.variables[output_variable] = '${activities.' + activity + '.output}'
        elif kind in {'bw.parse.parsedata', 'bw.parse.renderdata', 'bw.dataconversion.parsedata', 'bw.dataconversion.renderdata'}:
            parsing = kind.endswith('.parsedata')
            settings = value if value is not None else owner.find(BW + ('ParseData' if parsing else 'RenderData'))
            if settings is None: raise ValueError(f'{label}: missing Parse/Render Data configuration')
            options = {etree.QName(k).localname: v for k, v in settings.attrib.items() if not k.startswith('{')}
            for child in settings:
                if not isinstance(child.tag, str): continue
                if len(child) or child.attrib: raise ValueError(f'{label}: unsupported Data Format setting {etree.QName(child).localname}')
                options[etree.QName(child).localname] = (child.text or '').strip()
            reference = next((options.get(key) for key in ('dataFormatResource', 'dataFormat', 'dataFormatResourceName', 'sharedResourceProperty') if options.get(key)), None)
            variable = next((item for item in self.document.findall(f'{BPEL}variables/{BPEL}variable') if item.get('name') == reference), None)
            unbound = False
            if variable is not None:
                literal = (variable.findtext(f'{BPEL}from/{BPEL}literal') or
                           variable.get('{http://ns.tibco.com/bw/property}source'))
                unbound = not literal and variable.get(
                    '{http://docs.oasis-open.org/ns/opencsa/sca-bpel/200801}sharedResourceType') == '{http://ns.tibco.com/bw/palette/dataformat}DataFormat'
                reference = literal or reference
            try:
                format_id = self.resolve_resource(reference, 'data_format')
            except ValueError:
                if not unbound: raise
                format_id = 'bw-unbound:' + reference
                self.diagnostics.append(f'{label}: Data Format {reference!r} is unbound; select a shared Data Format before running.')
            config = {'operation': 'parse' if parsing else 'render', 'dataFormatId': format_id}
            if parsing:
                mode = options.get('inputType', options.get('inputSource', 'String')).lower()
                if mode not in ('string','file','text','file path'): raise ValueError(f'{label}: unsupported Parse Data input type')
                config['inputSource'] = 'File path' if mode.startswith('file') else 'String'
                for name, alias in (('skipBlankSpaces','skipBlankLines'), ('manuallySpecifyStartRecord','manualStartRecord'),
                                    ('manuallySpecifiedStartRecord','manualStartRecord'),
                                    ('strictValidation','strictColumns'), ('continueOnError','continueOnError')):
                    if name in options: config[alias] = options[name].lower() == 'true'
                if options.get('encoding'): config['fileEncoding'] = options['encoding']
            if binding is not None:
                root, fields = _binding_fields(binding)
                if parsing and not fields:
                    self.diagnostics.append(f'{label}: the BW input binding is empty; map the text or file in MINA Input.')
                else:
                    mapped = map_binding()
                    previous = self.connect(previous, mapped)
                    prefix = '${activities.' + mapped + '.output.' + root
                    if parsing:
                        allowed = {'text', 'fileName', 'startRecord', 'noOfRecords', 'SkipHeaderCharacters'}
                        if not fields <= allowed: raise ValueError(f'{label}: unsupported Parse Data input binding')
                        config['inputMappings'] = {
                            ('skipHeaderCharacters' if field == 'SkipHeaderCharacters' else field): prefix + '.' + field + '}'
                            for field in fields}
                    else:
                        config['Rows'] = prefix + ('.Rows' if 'Rows' in fields else '') + '}'
            activity = self.node('flat', label, config)
            self.variables[output_variable] = '${activities.' + activity + '.output' + ('.xmlString' if parsing else '.text') + '}'
        elif kind in {'bw.file.read', 'bw.file.readfile', 'bw.file.write'} and value is not None:
            root, fields = _binding_fields(binding)
            writing = kind == 'bw.file.write'
            allowed_fields = {'fileName', 'encoding', 'textContent', 'binaryContent'} if writing else {'fileName', 'encoding'}
            allowed_options = {XSI_TYPE, 'encoding', 'compressFile', 'createMissingDirectories', 'append', 'overwrite'}
            if (not fields <= allowed_fields or 'fileName' not in fields or set(value.attrib) - allowed_options
                    or len(value) or value.get('compressFile', 'None') != 'None'):
                raise ValueError(f'{label}: unsupported File activity binding or options')
            mode = value.get('encoding', 'text').lower()
            if mode not in {'binary', 'text'} or writing and ('binaryContent' if mode == 'binary' else 'textContent') not in fields:
                raise ValueError(f'{label}: unsupported file encoding or content')
            mapped = map_binding()
            previous = self.connect(previous, mapped)
            prefix = '${activities.' + mapped + '.output.' + root + '.'
            config = {'operation': 'write' if writing else 'read', 'path': prefix + 'fileName}',
                      'writeAs' if writing else 'readAs': mode}
            for key in fields - {'fileName'}:
                config[key] = prefix + key + '}'
            if writing:
                config.update(createDirectories=value.get('createMissingDirectories', 'false') == 'true',
                              append=value.get('append', 'false') == 'true', overwrite=value.get('overwrite', 'false') == 'true')
            activity = self.node('file', label, config)
        elif kind in {'bw.file.read', 'bw.file.readfile'}:
            config = _settings(owner.find(BW + 'ReadFile'), {'fileName', 'readAs', 'encoding', 'excludeFileContent'})
            path = config.get('fileName')
            if (binding is not None or not path or '${' in path or config.get('excludeFileContent', 'false') != 'false'
                    or config.get('readAs', 'text').lower() not in {'text', 'binary'}):
                raise ValueError(f'{label}: Read File requires a literal filename and supported read options')
            activity = self.node('file', label, {'operation': 'read', 'path': path, 'readAs': config.get('readAs', 'text'),
                                                  'encoding': config.get('encoding', 'utf-8')})
        elif kind in {'bw.http.sendhttprequest', 'bw.http.sendrequest'}:
            config = _settings(owner.find(BW + 'SendHTTPRequest'), {'httpClient', 'method', 'requestURI'})
            method, path = config.get('method', 'GET').upper(), config.get('requestURI', '')
            uri = urlsplit(path)
            if (binding is not None or method not in {'GET', 'HEAD'} or not path.startswith('/') or uri.netloc
                    or uri.scheme or uri.fragment or '${' in path or '\\' in path or not config.get('httpClient')):
                raise ValueError(f'{label}: expected a literal GET/HEAD and an HTTP client shared resource')
            resource = self.resolve_resource(config['httpClient'], 'http:client')
            self.resources.add(resource)
            activity = self.node('http', label, {'operation': 'request', 'method': method, 'path': path,
                                                'resourceId': resource, 'responseMode': 'envelope'})
        elif kind in {'bw.jdbc.jdbcquery', 'bw.jdbc.update', 'bw.jdbc.insert', 'bw.jdbc.delete'} and value is not None:
            operation = kind.rsplit('.', 1)[-1].replace('jdbcquery', 'query')
            if (set(value.attrib) - {XSI_TYPE, 'sharedResourceProperty', 'sqlStatement', 'maxRows', 'timeout'}
                    or any(child.tag not in {'PreparedParameters', 'columnMetadata'} for child in value)):
                raise ValueError(f'{label}: unsupported JDBC activity options')
            resource = self.connection(value.get('sharedResourceProperty'), 'jdbc')
            sql = value.get('sqlStatement')
            if not sql:
                raise ValueError(f'{label}: JDBC requires a static SQL statement')
            config = {'operation': operation, 'sql': sql, 'resourceId': resource}
            for key in ('timeout', 'maxRows'):
                if value.get(key) is not None:
                    config[key] = int(value.get(key))
            parameters = [parameter.get('ParameterName') for parameter in value.findall('PreparedParameters')]
            if binding is not None:
                root, fields = _binding_fields(binding)
                if set(parameters) != fields or len(fields) != len(parameters):
                    raise ValueError(f'{label}: unsupported JDBC parameter binding structure')
                mapped = map_binding()
                previous = self.connect(previous, mapped)
                config['parameters'] = ['${activities.' + mapped + '.output.' + root + '.' + name + '}' for name in parameters]
            elif parameters:
                raise ValueError(f'{label}: JDBC parameters require an input binding')
            activity = self.node('jdbc', label, config)
        elif kind in {'bw.jms.sendmessage', 'bw.jms.getqueuemessage'} and value is not None:
            sending = kind == 'bw.jms.sendmessage'
            config = self.jms_config(value, 'send_message' if sending else 'get_queue_message')
            if sending:
                root, fields = _binding_fields(binding)
                if fields not in ({'text'}, {'textContent'}):
                    raise ValueError(f'{label}: expected a single JMS text payload')
                mapped = map_binding()
                previous = self.connect(previous, mapped)
                config['data'] = '${activities.' + mapped + '.output.' + root + '.' + next(iter(fields)) + '}'
            elif binding is not None:
                raise ValueError(f'{label}: dynamic JMS receive bindings require review')
            activity = self.node('jms', label, config)
        else:
            raise ValueError(f'{label}: unsupported BW activity {kind or "(unspecified)"}')
        if kind not in {'bw.generalactivities.mapper', 'bw.generalactivities.map', 'bw.generalactivities.callprocess',
                        'bw.parse.parsedata', 'bw.parse.renderdata', 'bw.dataconversion.parsedata', 'bw.dataconversion.renderdata',
                        'bw.internal.end', *XML_JSON_FORMATS}:
            # Connector result shapes differ from the BW variable XML; demand an explicit adapter.
            self.variables[output_variable] = None
        return self.connect(previous, activity)
