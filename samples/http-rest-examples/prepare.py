"""Create local-only demo PKI and update certificate-folder properties in packages.
Run with a Python environment containing cryptography. No system trust is modified.
"""
import argparse,datetime,ipaddress,json,os,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def prepare():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
    local=ROOT/'local';local.mkdir(exist_ok=True)
    roots=local/'trusted-roots';roots.mkdir(exist_ok=True)
    now=datetime.datetime.now(datetime.timezone.utc)
    def issue(name,issuer=None,issuer_key=None,ca=False,client=False):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,name)])
        builder=x509.CertificateBuilder().subject_name(subject).issuer_name(issuer.subject if issuer else subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=5)).not_valid_after(now+datetime.timedelta(days=30)).add_extension(x509.BasicConstraints(ca=ca,path_length=1 if ca and issuer is None else 0 if ca else None),critical=True).add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False)
        builder=builder.add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key((issuer_key or key).public_key()),critical=False)
        builder=builder.add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,key_encipherment=not ca,data_encipherment=False,key_agreement=False,key_cert_sign=ca,crl_sign=ca,encipher_only=False,decipher_only=False),critical=True)
        if not ca:
            builder=builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH if client else ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
            if not client:builder=builder.add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
        return key,builder.sign(issuer_key or key,hashes.SHA256())
    def pem(cert):return cert.public_bytes(serialization.Encoding.PEM)
    def private(name,key):
        path=local/name;path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        if os.name!='nt':path.chmod(0o600)
    if not (roots/'root.pem').exists() or not all((local/name).exists() for name in ('server-chain.pem','server-key.pem','client-chain.pem','client-key.pem')):
        root_key,root=issue('MINA LOCAL DEMO ROOT',ca=True)
        inter_key,inter=issue('MINA LOCAL DEMO INTERMEDIATE',root,root_key,ca=True)
        server_key,server=issue('localhost',inter,inter_key)
        client_key,client=issue('MINA demo client',inter,inter_key,client=True)
        (roots/'root.pem').write_bytes(pem(root))
        (local/'server-chain.pem').write_bytes(pem(server)+pem(inter))
        (local/'client-chain.pem').write_bytes(pem(client)+pem(inter))
        private('server-key.pem',server_key);private('client-key.pem',client_key)
        # CA signing keys are intentionally not persisted.
    for package in sorted((ROOT/'projects').glob('*.mpackage')):
        with zipfile.ZipFile(package) as archive:members={item.filename:archive.read(item) for item in archive.infolist()}
        project=json.loads(members['project.json'])
        for values in project['properties'].values():
            for prop in values:
                if prop['key']=='demo.directory':prop['value']=local.as_posix()
        members['project.json']=json.dumps(project,indent=2).encode()
        temporary=package.with_suffix('.tmp')
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in members.items():archive.writestr(name,data)
        temporary.replace(package)
    print('Prepared 20 Studio packages. Import from:',ROOT/'projects')
    print('Only this root is trusted by sample clients:',roots/'root.pem')
    print('Certificates expire after 30 days. To renew, move the local folder aside and rerun prepare.py; then reimport or update project properties.')
    return local

if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    prepare()
