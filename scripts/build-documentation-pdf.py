"""Generate the offline manual from the web guide's exact content model."""
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, PageBreak
from reportlab.platypus.tableofcontents import TableOfContents


def text(value):
    value = re.sub(r'\*\*(.*?)\*\*', r'\1', str(value))
    return escape(value.translate(str.maketrans({'→': ' -> ', '—': '-', '–': '-', '…': '...', '−': '-', '’': "'", '“': '"', '”': '"'}))).replace('\n', '<br/>')


def build(source, destination):
    model = json.loads(Path(source).read_text(encoding='utf-8'))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Body', fontName='Helvetica', fontSize=9, leading=13, spaceAfter=7, wordWrap='CJK'))
    styles.add(ParagraphStyle(name='Cell', parent=styles['Body'], fontSize=8, leading=11, spaceAfter=0))
    styles.add(ParagraphStyle(name='CodeBlock', parent=styles['Body'], fontName='Courier', fontSize=8, leading=11, backColor=colors.HexColor('#eef3f8'), borderPadding=7, spaceBefore=6, spaceAfter=10))
    styles['Heading1'].textColor = colors.HexColor('#006b8c')
    styles['Heading1'].fontSize = 20
    styles['Heading1'].leading = 25
    styles['Heading2'].fontSize = 13
    styles['Heading2'].leading = 17
    styles['Heading3'].fontSize = 10
    styles['Heading3'].leading = 14
    class Manual(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            if isinstance(flowable, Paragraph) and hasattr(flowable, 'topic_key'):
                self.canv.bookmarkPage(flowable.topic_key)
                self.canv.addOutlineEntry(flowable.getPlainText(), flowable.topic_key, level=0, closed=False)
                self.notify('TOCEntry', (0, flowable.getPlainText(), self.page, flowable.topic_key))
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#51667b'))
        canvas.drawString(42, 24, f"MINA {model['version']} | Installed documentation | {model['fingerprint'][:12]}")
        canvas.drawRightString(553, 24, str(doc.page))
        canvas.restoreState()
    doc = Manual(str(destination), pagesize=(595,842), rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=44, title='MINA Product Documentation',author='MINA')
    story=[Paragraph('MINA',styles['Title']),Paragraph('Product documentation',styles['Heading1']),Paragraph('Mediation, Integration and Automation',styles['Heading2']),Spacer(1,20),Paragraph(text(f"Version {model['version']} - {model['counts']['activities']} activities, {model['counts']['groups']} groups, {model['counts']['functions']} functions and {model['counts']['connections']} shared connection types."),styles['Body']),Paragraph('This manual and the searchable web guide share the same content. Activity tables reflect base editor contracts; selected schemas and provider modes can add fields or requirements. Read the Security section before shared or production deployment.',styles['Body']),Paragraph('Use the PDF bookmarks or the linked table of contents to navigate. Content does not certify external providers, guarantee performance, or establish production security readiness.',styles['Body']),PageBreak(),Paragraph('Contents',styles['Title'])]
    toc=TableOfContents();toc.levelStyles=[ParagraphStyle(name='ContentsEntry',fontName='Helvetica',fontSize=9,leading=12,spaceBefore=3,leftIndent=0,rightIndent=30)]
    story.extend([toc,PageBreak()])
    for page in model['pages']:
        heading=Paragraph(text(page['title']),styles['Heading1']);heading.topic_key=page['id']
        story.extend([heading,Paragraph(text(page['category']),styles['Body'])])
        for section in page['sections']:
            story.append(Paragraph(text(section['title']),styles['Heading2']))
            for block in section['blocks']:
                kind=block['kind']
                if kind=='table':
                    columns=block['columns']; rows=block['rows']
                    if not rows:
                        story.append(Paragraph('No additional fields declared for this section.',styles['Body']));continue
                    widths=[150,110,251] if len(columns)==3 else [170,341] if len(columns)==2 else [511/len(columns)]*len(columns)
                    data=[[Paragraph(text(c),styles['Cell']) for c in columns]]
                    for row in rows:data.append([Paragraph(text(row[i] if i<len(row) else ''),styles['Cell']) for i in range(len(columns))])
                    table=LongTable(data,colWidths=widths,repeatRows=1,hAlign='LEFT',splitByRow=1,splitInRow=1)
                    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dfeef4')),('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#c5d1df')),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
                    story.extend([table,Spacer(1,9)])
                else:
                    style=styles['CodeBlock'] if kind=='code' else styles['Heading3'] if kind=='heading' else styles['Body']
                    story.append(Paragraph(('- ' if kind=='list' else '')+text(block['text']),style))
        if page.get('source'):story.append(Paragraph(text('Reference source: '+page['source']),styles['Body']))
        story.append(PageBreak())
    doc.multiBuild(story,onFirstPage=footer,onLaterPages=footer)
    from pypdf import PdfReader
    reader=PdfReader(str(destination))
    full='\n'.join(page.extract_text() or '' for page in reader.pages)
    if 'MINA' not in full or len(reader.pages)<len(model['pages']):raise RuntimeError('Incomplete PDF output')
    print(f"PDF: {len(reader.pages)} pages; {len(model['pages'])} indexed topics")


if __name__=='__main__':build(sys.argv[1],sys.argv[2])
