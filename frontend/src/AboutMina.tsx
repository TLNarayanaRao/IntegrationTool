import { useEffect, useState } from 'react';
import { Workflow } from 'lucide-react';
import './about-mina.css';

export default function AboutMina() {
  const desktop = !!window.minaDesktop;
  const [version, setVersion] = useState(String(import.meta.env.VITE_APP_VERSION || 'Development'));
  const [source, setSource] = useState('Studio UI build');
  useEffect(() => {
    let active = true;
    window.minaDesktop?.getAppInfo?.().then(info => {
      if (active && info.packaged && info.version) { setVersion(info.version); setSource('Installed application'); }
    }).catch(() => { /* Older desktop hosts can still display the UI build version. */ });
    return () => { active = false; };
  }, []);
  return <section className="mina-about" aria-label="MINA product information">
    <Workflow aria-hidden="true"/><h2>MINA Studio</h2>
    <p className="mina-about-tagline">Mediation, Integration &amp; Automation</p>
    <p>Design, test and deliver integration applications with a visual workflow designer and a Python-based runtime.</p>
    <dl>
      <div><dt>Product version</dt><dd>{version}</dd></div>
      <div><dt>Version source</dt><dd>{source}</dd></div>
      <div><dt>Interface</dt><dd>{desktop ? 'Desktop application' : 'Web browser'}</dd></div>
    </dl>
    <p className="mina-about-note">This is the MINA product version, not your project's deployment version.</p>
    <ul><li>Visual mediation, mapping and transformation</li><li>Messaging, APIs, databases and enterprise connectors</li><li>Run, debug and activity testing</li><li>Application packaging and Control Plane deployment</li></ul>
    <a href="/help/index.html" target="_blank" rel="noopener noreferrer">Open product documentation ↗</a>
  </section>;
}
