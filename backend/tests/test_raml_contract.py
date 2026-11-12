import copy
import unittest
from unittest.mock import patch
from app.api_blueprint import validate_blueprint, blueprint_plan

RAML='''#%RAML 1.0
title: Library API
version: v1
baseUri: http://localhost/{version}
mediaType: application/json
uses:
  lib: libraries/common.raml
/books:
  type:
    lib.collection:
      itemType: lib.Book
      exampleValue: [{id: "42", title: API design}]
  is: [lib.paged]
  get:
    (operationId): books
    queryParameters:
      page?: {type: integer, minimum: 2}
  /{book-id}:
    get:
      (operationId): book
      responses:
        200:
          body:
            type: lib.Book
            example: !include examples/book.json
'''
LIBRARY='''#%RAML 1.0 Library
types:
  Book:
    type: object
    properties:
      id: string
      title: string
      note?: string | nil
traits:
  paged:
    queryParameters:
      page?: {type: integer, minimum: 1}
resourceTypes:
  collection:
    description: Collection of <<resourcePathName | !singularize>> items
    get:
      responses:
        200:
          body:
            type: <<itemType>>[]
            example: <<exampleValue>>
    post?:
      body: {type: <<itemType>>}
      responses: {201: {description: Created}}
'''
REFERENCES={'libraries/common.raml':LIBRARY,'examples/book.json':'{"id":"42","title":"API design"}'}


class RAMLContractTests(unittest.TestCase):
    def test_traits_libraries_resource_types_and_nested_routes_expand_offline(self):
        with patch('app.http_transport.client_for',side_effect=AssertionError('No network')):
            result=validate_blueprint(RAML,reference_documents=REFERENCES,document_path='api.raml')
        self.assertEqual([operation['operationId'] for operation in result['operations']],['books','book'])
        spec=result['document']
        self.assertIn('lib.Book',spec['components']['schemas'])
        self.assertNotIn('post',spec['paths']['/books'])
        page=spec['paths']['/books']['get']['parameters'][0]
        self.assertEqual(page['schema']['minimum'],2)
        self.assertFalse(page['required'])
        self.assertEqual(spec['servers'][0]['url'],'http://localhost/v1')
        plan=blueprint_plan(RAML,['books','book'],{'type':'http','config':{}},response_mode='example',reference_documents=REFERENCES,document_path='api.raml')
        self.assertEqual(plan['tasks'][0]['activities'][1]['config']['statusCode'],200)

    def test_optional_methods_only_expand_when_present(self):
        document=RAML.replace('  get:\n    (operationId): books','  post:\n  get:\n    (operationId): books')
        result=validate_blueprint(document,reference_documents=REFERENCES,document_path='api.raml')
        self.assertIn('post',result['document']['paths']['/books'])
        self.assertTrue(result['document']['paths']['/books']['post']['requestBody'])

    def test_nested_libraries_and_type_inheritance(self):
        references=copy.deepcopy(REFERENCES)
        references['libraries/common.raml']=LIBRARY.replace('types:\n','uses:\n  core: core.raml\ntypes:\n',1).replace('type: object','type: core.Entity',1)
        references['libraries/core.raml']='#%RAML 1.0 Library\ntypes:\n  Entity:\n    type: object\n    properties:\n      id: string\n'
        result=validate_blueprint(RAML,reference_documents=references,document_path='api.raml')
        self.assertIn('lib.core.Entity',result['document']['components']['schemas'])

    def test_missing_includes_cycles_unsupported_tags_and_duplicate_keys_fail(self):
        for refs in ({}, {**REFERENCES,'libraries/common.raml':LIBRARY.replace('type: object','type: Missing',1)},
                     {**REFERENCES,'libraries/common.raml':'#%RAML 1.0 Library\nuses: {loop: common.raml}\n'}):
            with self.subTest(refs=list(refs)),self.assertRaises(ValueError):validate_blueprint(RAML,reference_documents=refs,document_path='api.raml')
        for document in ('#%RAML 1.0\ntitle: One\ntitle: Two\n', '#%RAML 1.0\ntitle: Test\n/x: !include ../private.yaml',
                         '#%RAML 1.0\ntitle: !!python/object/apply:os.system [echo unsafe]'):
            with self.assertRaises(ValueError):validate_blueprint(document,document_path='api.raml')

    def test_trait_parameter_functions_and_union_collection_merge(self):
        document='''#%RAML 1.0
title: Traits
traits:
  filter:
    queryParameters:
      <<field>>?: {enum: [win, mac]}
resourceTypes:
  basic:
    get:
      responses: {200: {description: OK}}
/users:
  type: basic
  get:
    is: [{filter: {field: platform}}]
    queryParameters:
      platform?: {enum: [mac, unix]}
'''
        result=validate_blueprint(document)
        values=result['document']['paths']['/users']['get']['parameters'][0]['schema']['enum']
        self.assertEqual(values,['mac','unix','win'])

    def test_json_schema_includes_resolve_their_own_local_references(self):
        document='''#%RAML 1.0
title: Included schema
types:
  Item: !include schemas/item.json
/items:
  get:
    responses:
      200:
        body:
          application/json:
            type: Item
            example: {name: ready}
'''
        refs={'schemas/item.json':'{"$schema":"http://json-schema.org/draft-07/schema#","type":"object","properties":{"name":{"$ref":"#/definitions/Name"}},"definitions":{"Name":{"type":"string"}}}'}
        self.assertTrue(validate_blueprint(document,reference_documents=refs,document_path='api.raml')['operations'][0]['hasExample'])

    def test_trait_fragment_can_import_its_own_library(self):
        document='''#%RAML 1.0
title: Fragment
traits:
  paged: !include traits/paged.raml
/items:
  get:
    is: [paged]
    responses: {204: {description: Empty}}
'''
        refs={'traits/paged.raml':'#%RAML 1.0 Trait\nuses:\n  lib: ../types.raml\nqueryParameters:\n  count?: lib.Count\n',
              'types.raml':'#%RAML 1.0 Library\ntypes:\n  Count: {type: integer, minimum: 1}\n'}
        self.assertTrue(validate_blueprint(document,reference_documents=refs,document_path='api.raml')['operations'])

    def test_optional_resource_method_does_not_require_unused_parameters(self):
        document='''#%RAML 1.0
title: Optional
resourceTypes:
  basic:
    get: {responses: {204: {description: Empty}}}
    post?: {description: <<missing>>}
/items:
  type: basic
'''
        self.assertEqual(len(validate_blueprint(document)['operations']),1)
        with self.assertRaisesRegex(ValueError,'Missing RAML template parameter'):
            validate_blueprint(document+'  post:\n')

    def test_raml_protocol_restrictions_and_basic_security_are_enforced(self):
        document='''#%RAML 1.0
title: Secure
protocols: [HTTPS]
securitySchemes:
  basic: {type: Basic Authentication}
securedBy: [basic]
/items:
  get: {responses: {204: {description: Empty}}}
'''
        selected=[item['operationId'] for item in validate_blueprint(document)['operations']]
        with self.assertRaises(ValueError):blueprint_plan(document,selected,{'type':'http','config':{}})
        plan=blueprint_plan(document,selected,{'type':'http','config':{'scheme':'https','authentication':'Basic','username':'user','password':'test'}})
        self.assertTrue(plan['tasks'])


if __name__=='__main__':unittest.main()
