"""Compile and execute real Java bridge connection-selection regressions."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
import asyncio
from unittest.mock import patch

from app.models import SharedResource
from app.runtime import WorkflowRuntime
from app.faults import MinaFault

ROOT=Path(__file__).resolve().parents[2]
JAVAC=shutil.which('javac')
JAVA=str(Path(JAVAC).with_name('java.exe' if os.name=='nt' else 'java')) if JAVAC else None


class JmsCredentialValidationTests(unittest.TestCase):
    def context(self,kind,config):
        return {'resources':{'c':SharedResource(id='c',name='QA',type=kind,config=config)},'last':{},'input':{},'properties':{},'vars':{},'context':{},'activities':{},'tasks':{},'logs':[]}

    def test_provider_authentication_is_optional_and_credentials_are_preserved(self):
        async def exercise():
            for kind in ('jms','ems'):
                for credentials in ({},{'username':'','password':''},{'username':'alice','password':''},{'username':'alice','password':'test-only'}):
                    config={'serverUrl':'tcp://test.invalid:1',**credentials}
                    with patch('app.runtime.execute_jms',return_value={'published':True,'messageId':'test'}) as send:
                        await WorkflowRuntime().messaging(kind,{'resourceId':'c','operation':'send_message' if kind=='jms' else 'send','destination':'qa','message':'test'},self.context(kind,config))
                        actual=send.call_args.args[0]
                        for key,value in credentials.items():self.assertEqual(actual[key],value)
        asyncio.run(exercise())

    def test_jndi_does_not_require_direct_url_or_naming_credentials(self):
        async def exercise():
            for kind in ('jms','ems'):
                config={'connectionFactoryType':'JNDI','jndiProviderUrl':'test://qa','connectionFactory':'QAFactory'}
                if kind=='jms':config['jndiContextFactory']='qa.Factory'
                with patch('app.runtime.execute_jms',return_value={'published':True,'messageId':'test'}) as send:
                    await WorkflowRuntime().messaging(kind,{'resourceId':'c','operation':'send','destination':'qa'},self.context(kind,config))
                    send.assert_called_once()
                for field in ('jndiProviderUrl','connectionFactory'):
                    with self.assertRaises(MinaFault):await WorkflowRuntime().messaging(kind,{'resourceId':'c','operation':'send'},self.context(kind,{k:v for k,v in config.items() if k!=field}))
        asyncio.run(exercise())


@unittest.skipUnless(JAVAC and JAVA and Path(JAVA).is_file(),'A matching Java compiler/runtime is required')
class JmsConnectionAuthenticationTests(unittest.TestCase):
    def test_provider_defaults_explicit_credentials_and_public_interface_reflection(self):
        source=ROOT/'java-bridge/src/com/mina/bridge/MinaJavaBridge.java'
        tests=ROOT/'java-bridge/test/com/mina/bridge'
        with tempfile.TemporaryDirectory() as folder:
            result=subprocess.run([JAVAC,'-encoding','UTF-8','-d',folder,str(source),
                str(tests/'MinaJavaBridgeAuthenticationTest.java'),str(tests/'MinaJavaBridgeReflectionTest.java')],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr)
            for name in ('MinaJavaBridgeAuthenticationTest','MinaJavaBridgeReflectionTest'):
                result=subprocess.run([JAVA,'-cp',folder,'com.mina.bridge.'+name],capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
