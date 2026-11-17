"""Self-contained XSLT 3.0 implementations for JSON-valued Mapper functions.

No extension calls, filesystem imports, or Python callbacks are used. JSON is
carried in XML text fields at the XML boundary; inside functions it is XDM data.
"""
import json
from functools import lru_cache
from .mapper_xml import XSL, etree

URI = 'urn:mina:mapper:documents:1'
NAMES = {'jsonpointer', 'jsonpatch', 'jsonmergepatch', 'jsondiff', 'joinrecords',
         'deduplicaterecords', 'redactkeys', 'masktext', 'reconcilerecords', 'aggregaterecords'}
NS = {'md': URI, 'map': 'http://www.w3.org/2005/xpath-functions/map',
      'array': 'http://www.w3.org/2005/xpath-functions/array',
      'xs': 'http://www.w3.org/2001/XMLSchema'}


@lru_cache(maxsize=1)
def _casefold_table():
    # Embed Unicode casefold exceptions so Saxon and Python match for non-ASCII
    # field names as well. Ordinary lowercase remains the processor's operation.
    return 'map{' + ','.join(str(i) + ':codepoints-to-string((' + ','.join(str(ord(c)) for c in chr(i).casefold()) + '))'
                            for i in range(0x110000) if chr(i).casefold() != chr(i).lower()) + '}'


def install(binding):
    """Embed deterministic, portable function declarations in a generated binding."""
    etree.SubElement(binding, XSL + 'variable', name='md:casefold', select=_casefold_table())
    def function(name, params, expression):
        node = etree.SubElement(binding, XSL + 'function', name='md:' + name,
                                nsmap=NS, attrib={'as': 'item()*'})
        for param in params.split(): etree.SubElement(node, XSL + 'param', name=param)
        etree.SubElement(node, XSL + 'sequence', select=expression)

    function('fail', 'message', "error(QName('urn:mina:mapper:documents:1', 'md:INVALID'), $message)")
    function('number', 's', """if (not(contains(lower-case($s),'e'))) then xs:decimal($s) else
      (let $parts := tokenize(lower-case($s),'e'), $e := xs:integer($parts[2]), $m := replace($parts[1],'^-',''),
      $digits := replace($m,'\\.',''), $p := (if (contains($m,'.')) then string-length(substring-before($m,'.')) else string-length($m)) + $e
      return if (abs($e) gt 1000) then md:fail('Numeric exponent exceeds 1000') else
      xs:decimal(concat(if (starts-with($s,'-')) then '-' else '',
        if ($p le 0) then concat('0.',string-join(for $i in 1 to (-$p) return '0',''),$digits)
        else if ($p ge string-length($digits)) then concat($digits,string-join(for $i in 1 to ($p - string-length($digits)) return '0',''))
        else concat(substring($digits,1,$p),'.',substring($digits,$p+1)))))""")
    function('text', 'v', "if (empty($v) or $v instance of map(*) or $v instance of array(*)) then serialize($v,map{'method':'json'}) else string($v)")
    function('bytes', 'v', "sum(for $c in string-to-codepoints(serialize($v,map{'method':'json'})) return if ($c lt 128) then 1 else if ($c lt 2048) then 2 else if ($c lt 65536) then 3 else 4)")
    function('json', 'v', "if ($v instance of node()) then parse-json(string($v), map{'duplicates':'reject', 'number-parser':md:number#1}) else $v")
    function('size', 'v depth', "if ($depth gt 128) then md:fail('JSON depth exceeds 128') else 1 + (if ($v instance of map(*)) then sum(for $k in map:keys($v) return md:size($v($k), $depth+1)) else if ($v instance of array(*)) then sum(for $i in 1 to array:size($v) return md:size($v($i), $depth+1)) else 0)")
    function('check', 'v', "if (md:size($v,0) gt 4000000 or md:bytes($v) gt 8388608) then md:fail('JSON transformation exceeds resource bounds') else $v")
    function('parts', 'p', "if (not($p instance of xs:string) or string-length($p) gt 8192 or (not($p='') and not(starts-with($p,'/'))) or matches($p,'~[^01]|~$')) then md:fail('Invalid JSON Pointer') else if ($p='') then () else if ($p='/') then '' else tokenize(substring($p,2),'/') ! replace(replace(.,'~1','/'),'~0','~')")
    # URI fragments are decoded through UTF-8 percent bytes without external I/O.
    function('utf8', 'bytes', "if (empty($bytes)) then () else if ($bytes[1] lt 128) then ($bytes[1],md:utf8(subsequence($bytes,2))) else if ($bytes[1] ge 194 and $bytes[1] le 244) then (let $n := (if ($bytes[1] lt 224) then 2 else if ($bytes[1] lt 240) then 3 else 4), $tail := subsequence($bytes,2,$n - 1), $c := ($bytes[1] mod (if ($n=2) then 32 else if ($n=3) then 16 else 8)) * (if ($n=2) then 64 else if ($n=3) then 4096 else 262144) + sum(for $i in 1 to count($tail) return ($tail[$i] - 128) * (if ($n - $i=1) then 1 else if ($n - $i=2) then 64 else 4096)) return if (count($tail) ne $n - 1 or (some $b in $tail satisfies ($b lt 128 or $b gt 191)) or $c lt (if ($n=2) then 128 else if ($n=3) then 2048 else 65536) or $c gt 1114111 or ($c ge 55296 and $c le 57343)) then md:fail('Invalid UTF-8 fragment') else ($c,md:utf8(subsequence($bytes,$n+1)))) else md:fail('Invalid UTF-8 fragment')")
    function('unquote', 's', "if ($s='') then '' else if (starts-with($s,'%')) then (let $run := replace($s,'^((%[0-9A-Fa-f]{2})+).*','$1'), $hex := '0123456789abcdef', $bytes := for $i in 1 to (string-length($run) idiv 3) return (string-length(substring-before($hex,lower-case(substring($run,3*$i - 1,1))))*16 + string-length(substring-before($hex,lower-case(substring($run,3*$i,1))))) return if (not(matches($s,'^%[0-9A-Fa-f]{2}'))) then md:fail('Invalid percent escape') else concat(codepoints-to-string(md:utf8($bytes)),md:unquote(substring($s,string-length($run)+1)))) else concat(substring($s,1,1),md:unquote(substring($s,2)))")
    function('index', 'k n add', "if ($k='-' and $add) then $n+1 else if (not(matches($k,'^(0|[1-9][0-9]*)$'))) then md:fail('Invalid JSON array index') else if (string-length($k) gt 10 or xs:integer($k) gt $n - (if ($add) then 0 else 1)) then md:fail('JSON array index outside document') else xs:integer($k)+1")
    function('get', 'v parts', "if (empty($parts)) then map{'exists':true(),'value':$v} else if ($v instance of map(*)) then (if (map:contains($v,$parts[1])) then md:get($v($parts[1]),subsequence($parts,2)) else map{'exists':false()}) else if ($v instance of array(*)) then (if ($parts[1]='-' or (matches($parts[1],'^(0|[1-9][0-9]*)$') and (string-length($parts[1]) gt 10 or xs:integer($parts[1]) ge array:size($v)))) then map{'exists':false()} else md:get($v(md:index($parts[1],array:size($v),false())),subsequence($parts,2))) else map{'exists':false()}")
    function('required', 'state parts', "let $found := if ($state?exists) then md:get($state?value,$parts) else map{'exists':false()} return if ($found?exists) then $found?value else md:fail('JSON Pointer target does not exist')")
    function('equal', 'a b', "if (empty($a) or empty($b)) then empty($a) and empty($b) else if ($a instance of map(*) and $b instance of map(*)) then map:size($a)=map:size($b) and (every $k in map:keys($a) satisfies (map:contains($b,$k) and md:equal($a($k),$b($k)))) else if ($a instance of array(*) and $b instance of array(*)) then array:size($a)=array:size($b) and (every $i in 1 to array:size($a) satisfies md:equal($a($i),$b($i))) else if (($a instance of xs:numeric and $b instance of xs:numeric) or ($a instance of xs:string and $b instance of xs:string) or ($a instance of xs:boolean and $b instance of xs:boolean)) then $a eq $b else false()")
    function('edit', 'v parts op value', "let $k := $parts[1], $rest := subsequence($parts,2) return if ($v instance of map(*)) then (if (($op ne 'add' or exists($rest)) and not(map:contains($v,$k))) then md:fail('JSON Patch member missing') else if (exists($rest)) then map:put($v,$k,md:edit($v($k),$rest,$op,$value)) else if ($op='remove') then map:remove($v,$k) else map:put($v,$k,$value)) else if ($v instance of array(*)) then (let $i := md:index($k,array:size($v),$op='add' and empty($rest)) return if (exists($rest)) then array:put($v,$i,md:edit($v($i),$rest,$op,$value)) else if ($op='remove') then array:remove($v,$i) else if ($op='add') then array:insert-before($v,$i,$value) else array:put($v,$i,$value)) else md:fail('JSON Patch parent is not a container')")
    function('change', 'state parts op value', "if (empty($parts)) then (if ($op ne 'add' and not($state?exists)) then md:fail('JSON root missing') else map{'exists':$op ne 'remove','value':if ($op='remove') then () else md:check($value)}) else if (not($state?exists)) then md:fail('JSON root missing') else map{'exists':true(),'value':md:check(md:edit($state?value,$parts,$op,$value))}")
    function('patch-one', 'state op', "if (not($op instance of map(*)) or not($op?op=('add','remove','replace','move','copy','test')) or not(map:contains($op,'path')) or ($op?op=('add','replace','test') and not(map:contains($op,'value')))) then md:fail('Invalid JSON Patch operation') else (let $p := md:parts($op?path) return if ($op?op='test') then (if (md:equal(md:required($state,$p),$op?value)) then $state else md:fail('JSON Patch test failed')) else if ($op?op=('copy','move')) then (let $from := md:parts($op?from), $v := md:required($state,$from) return if ($op?op='move' and deep-equal($from,$p)) then $state else if ($op?op='move' and count($p) gt count($from) and deep-equal(subsequence($p,1,count($from)),$from)) then md:fail('Cannot move into descendant') else md:change(if ($op?op='move') then md:change($state,$from,'remove',()) else $state,$p,'add',$v)) else md:change($state,$p,$op?op,$op?value))")
    function('merge', 'v patch', "if (not($patch instance of map(*))) then $patch else fold-left(sort(map:keys($patch)),if ($v instance of map(*)) then $v else map{},function($a,$k){if (empty($patch($k))) then map:remove($a,$k) else map:put($a,$k,md:merge($a($k),$patch($k)))})")
    function('escape', 'key', "replace(replace($key,'~','~0'),'/','~1')")
    function('diff', 'a b path', "if (md:equal($a,$b)) then [] else if ($a instance of map(*) and $b instance of map(*)) then array:join((for $k in sort(map:keys($a)[not(map:contains($b,.))]) return [map{'op':'remove','path':concat($path,'/',md:escape($k))}],for $k in sort(map:keys($b)[not(map:contains($a,.))]) return [map{'op':'add','path':concat($path,'/',md:escape($k)),'value':$b($k)}],for $k in sort(map:keys($a)[map:contains($b,.)]) return md:diff($a($k),$b($k),concat($path,'/',md:escape($k))))) else [map{'op':'replace','path':$path,'value':$b}]")
    function('keys', 'keys', "let $a := if ($keys instance of xs:string) then [$keys] else $keys return if (not($a instance of array(*)) or array:size($a) lt 1 or array:size($a) gt 16) then md:fail('Supply one to sixteen key paths') else array{for $i in 1 to array:size($a) return [md:parts($a($i))]}")
    function('key', 'row keys', "let $values := for $i in 1 to array:size($keys) return md:get($row,$keys($i)?*) return if (some $v in $values satisfies (not($v?exists) or empty($v?value))) then () else if (some $v in $values satisfies ($v?value instance of map(*) or $v?value instance of array(*))) then md:fail('Record keys must be scalar') else serialize(array{for $v in $values return (if ($v?value instance of xs:numeric) then ['number',string(xs:decimal($v?value))] else if ($v?value instance of xs:boolean) then ['boolean',$v?value] else ['string',$v?value])},map{'method':'json'})")
    function('rows', 'rows', "if (not($rows instance of array(*)) or array:size($rows) gt 100000) then md:fail('Expected up to 100000 records') else md:check($rows)")
    function('index-records', 'rows keys', "fold-left(1 to array:size($rows),map{},function($m,$i){let $k := md:key($rows($i),$keys) return if (empty($k)) then $m else map:put($m,$k,($m($k),$i))})")
    function('join', 'left right lk rk mode', "if (not($mode=('inner','left','right','full','semi','anti'))) then md:fail('Invalid join mode') else (let $l := md:rows($left), $r := md:rows($right), $index := md:index-records($r,$rk), $lindex := if ($mode=('right','full')) then md:index-records($l,$lk) else map{}, $count := sum(for $i in 1 to array:size($l) return (let $k := md:key($l($i),$lk), $hits := if (exists($k)) then $index($k) else () return if ($mode='semi') then xs:integer(exists($hits)) else if ($mode='anti') then xs:integer(empty($hits)) else if (exists($hits)) then count($hits) else xs:integer($mode=('left','full')))) + (if ($mode=('right','full')) then count(for $j in 1 to array:size($r) return (let $k := md:key($r($j),$rk) return if (empty($k) or not(map:contains($lindex,$k))) then $j else ())) else 0) return if ($count gt 100000) then md:fail('Join exceeds 100000 output rows') else (let $lbytes := array{for $i in 1 to array:size($l) return md:bytes($l($i))}, $rbytes := array{for $i in 1 to array:size($r) return md:bytes($r($i))}, $bytes := 2 + sum(for $i in 1 to array:size($l) return (let $k := md:key($l($i),$lk), $hits := if (exists($k)) then $index($k) else () return if ($mode=('semi','anti')) then (if (($mode='semi')=exists($hits)) then $lbytes($i)+1 else 0) else if (exists($hits)) then sum(for $j in $hits return $lbytes($i)+$rbytes($j)+20) else if ($mode=('left','full')) then $lbytes($i)+24 else 0)) + (if ($mode=('right','full')) then sum(for $j in 1 to array:size($r) return (let $k := md:key($r($j),$rk) return if (empty($k) or not(map:contains($lindex,$k))) then $rbytes($j)+24 else 0)) else 0) return if ($bytes gt 8388608) then md:fail('Join output exceeds 8 MiB') else array:join((for $i in 1 to array:size($l) return (let $k := md:key($l($i),$lk), $hits := if (exists($k)) then $index($k) else () return if ($mode=('semi','anti')) then (if (($mode='semi')=exists($hits)) then [$l($i)] else []) else if (exists($hits)) then array{for $j in $hits return map{'left':$l($i),'right':$r($j)}} else if ($mode=('left','full')) then [map{'left':$l($i),'right':()}] else []),if ($mode=('right','full')) then array{for $j in 1 to array:size($r) return (let $k := md:key($r($j),$rk) return if (empty($k) or not(map:contains($lindex,$k))) then map{'left':(),'right':$r($j)} else ())} else []))))")
    function('dedup', 'rows keys keep', "if (not($keep=('first','last'))) then md:fail('Expected first or last') else (let $r := md:rows($rows), $index := md:index-records($r,$keys) return array:join(for $i in 1 to array:size($r) return (let $k := md:key($r($i),$keys) return if (empty($k) or $i=(if ($keep='first') then $index($k)[1] else $index($k)[last()])) then [$r($i)] else [])))")
    function('foldcase', 's', "string-join(for $c in string-to-codepoints($s) return if (map:contains($md:casefold,$c)) then $md:casefold($c) else lower-case(codepoints-to-string($c)),'')")
    function('redact-bytes', 'v names replacement-bytes', "if ($v instance of map(*)) then 2 + sum(for $k in map:keys($v) return md:bytes($k)+2+(if (md:foldcase($k)=$names) then $replacement-bytes else md:redact-bytes($v($k),$names,$replacement-bytes))) else if ($v instance of array(*)) then 2 + sum(for $i in 1 to array:size($v) return 1+md:redact-bytes($v($i),$names,$replacement-bytes)) else md:bytes($v)")
    function('redact', 'v names replacement', "if ($v instance of map(*)) then map:merge(for $k in map:keys($v) return map:entry($k,if (md:foldcase($k)=$names) then $replacement else md:redact($v($k),$names,$replacement))) else if ($v instance of array(*)) then array:join(for $i in 1 to array:size($v) return [md:redact($v($i),$names,$replacement)]) else $v")
    _install_records(function)
    function('call', 'name input args', """let $v := md:check(if ($name='masktext' and $input instance of node()) then string($input) else md:json($input)), $n := array:size($args), $a := if ($n ge 1) then $args(1) else (), $b := if ($n ge 2) then $args(2) else (), $c := if ($n ge 3) then $args(3) else () return md:check(
      if ($name='jsonpointer') then (if ($n=(1,2)) then (let $p := if ($a instance of node()) then string($a) else $a, $found := md:get($v,md:parts(if (starts-with($p,'#')) then md:unquote(substring($p,2)) else $p)) return if ($found?exists) then $found?value else if ($n=2) then md:json($b) else md:fail('JSON Pointer target missing')) else md:fail('jsonPointer arity'))
      else if ($name='jsonpatch') then (let $ops := md:check(md:json($a)) return if ($n ne 1 or not($ops instance of array(*)) or array:size($ops) gt 10000) then md:fail('Invalid patch operations') else fold-left(1 to array:size($ops),map{'exists':true(),'value':$v},function($state,$i){md:patch-one($state,$ops($i))})?value)
      else if ($name='jsonmergepatch') then (if ($n=1) then md:merge($v,md:check(md:json($a))) else md:fail('jsonMergePatch arity'))
      else if ($name='jsondiff') then (if ($n=1) then (let $diff := md:diff($v,md:check(md:json($a)),'') return if (array:size($diff) gt 10000) then md:fail('Too many diff operations') else $diff) else md:fail('jsonDiff arity'))
      else if ($name='joinrecords') then (if ($n=(3,4)) then (let $lk := md:keys(md:json($b)), $rk := md:keys(md:json($c)) return if (array:size($lk) ne array:size($rk)) then md:fail('Join key counts must match') else md:join($v,md:json($a),$lk,$rk,if ($n=4) then string($args(4)) else 'inner')) else md:fail('joinRecords arity'))
      else if ($name='deduplicaterecords') then (if ($n=(1,2)) then md:dedup($v,md:keys(md:json($a)),if ($n=2) then string($b) else 'first') else md:fail('deduplicateRecords arity'))
      else if ($name='reconcilerecords') then (if ($n=2) then md:reconcile($v,md:json($a),md:keys(md:json($b))) else md:fail('reconcileRecords arity'))
      else if ($name='aggregaterecords') then (if ($n=2) then md:aggregate($v,md:keys(md:json($a)),md:json($b)) else md:fail('aggregateRecords arity'))
      else if ($name='redactkeys') then (let $names := md:json($a) return if (not($n=(1,2)) or not($names instance of array(*)) or array:size($names) lt 1 or array:size($names) gt 1024 or (some $i in 1 to array:size($names) satisfies not($names($i) instance of xs:string))) then md:fail('Invalid redaction names') else (let $folded := $names?* ! md:foldcase(.), $replacement := md:check(if ($n=2) then md:json($b) else '[REDACTED]') return if (md:redact-bytes($v,$folded,md:bytes($replacement)) gt 8388608) then md:fail('Redacted output exceeds 8 MiB') else md:redact($v,$folded,$replacement)))
      else if ($name='masktext') then (let $s := if ($input instance of node()) then string($input) else $input, $suffix := if ($n ge 1) then (if ($a instance of node()) then xs:integer(string($a)) else $a) else 4, $marker := if ($n=2) then string($b) else '*' return if ($n gt 2 or (exists($s) and not($s instance of xs:string)) or not($suffix instance of xs:integer) or $suffix lt 0 or string-length($marker) ne 1 or string-length($s) gt 65536) then md:fail('Invalid text mask') else if (empty($s)) then () else concat(string-join(for $i in 1 to max((0,string-length($s)-$suffix)) return $marker,''),substring($s,max((1,string-length($s)-$suffix+1)))))
      else md:fail('Unknown document function'))""")
    for name, arities in {'jsonPointer': (2, 3), 'jsonPatch': (2,), 'jsonMergePatch': (2,),
                          'jsonDiff': (2,), 'joinRecords': (4, 5), 'deduplicateRecords': (2, 3),
                          'redactKeys': (2, 3), 'maskText': (1, 2, 3),
                          'reconcileRecords': (3,), 'aggregateRecords': (3,)}.items():
        for arity in arities:
            params = ['v'] + ['a' + str(i) for i in range(1, arity)]
            function(name, ' '.join(params), "md:call('" + name.lower() + "', $v, [" + ', '.join('$' + p for p in params[1:]) + '])')


def _install_records(function):
    function('object-rows', 'rows', "let $r := md:rows($rows) return if (some $i in 1 to array:size($r) satisfies not($r($i) instance of map(*))) then md:fail('Expected record objects') else $r")
    function('strict-index', 'rows keys unique', """fold-left(1 to array:size($rows),map{},function($m,$i){
      let $k := md:key($rows($i),$keys) return
      if (empty($k)) then md:fail('Record keys must exist and be non-null scalars')
      else if ($unique and map:contains($m,$k)) then md:fail('Duplicate record key in snapshot')
      else map:put($m,$k,($m($k),$i))})""")
    function('record-key-values', 'row keys', "array{for $i in 1 to array:size($keys) return md:get($row,$keys($i)?*)?value}")
    function('record-emit', 'state kind value', "let $bytes := $state?bytes + md:bytes($value) + 1 return if ($bytes gt 8388608) then md:fail('Record output exceeds 8 MiB') else map:put(map:put($state,$kind,array:append($state($kind),$value)),'bytes',$bytes)")
    function('reconcile', 'before after keys', """let $b := md:object-rows($before), $a := md:object-rows($after),
      $bi := md:strict-index($b,$keys,true()), $ai := md:strict-index($a,$keys,true()) return
      if (map:size($bi) ne array:size($b) or map:size($ai) ne array:size($a)) then md:fail('Duplicate record key') else
      (let $state := fold-left(1 to array:size($a),map{'inserted':[],'updated':[],'deleted':[],'unchanged':[],'bytes':64},function($s,$i){
        let $j := $bi(md:key($a($i),$keys)) return if (empty($j)) then md:record-emit($s,'inserted',$a($i))
        else if (md:equal($b($j),$a($i))) then md:record-emit($s,'unchanged',$a($i))
        else md:record-emit($s,'updated',map{'key':md:record-key-values($a($i),$keys),'before':$b($j),'after':$a($i)})}),
      $final := fold-left(1 to array:size($b),$state,function($s,$j){if (not(map:contains($ai,md:key($b($j),$keys)))) then md:record-emit($s,'deleted',$b($j)) else $s})
      return md:check(map:remove($final,'bytes')))""")
    function('metric-specs', 'metrics', """let $m := md:check($metrics) return
      if (not($m instance of array(*)) or array:size($m) lt 1 or array:size($m) gt 16) then md:fail('Supply one to sixteen aggregate metrics')
      else (let $specs := array{for $i in 1 to array:size($m) return (let $s := $m($i) return
        if (not($s instance of map(*))) then md:fail('Metric must be an object')
        else if ((some $k in map:keys($s) satisfies not($k=('name','op','path'))) or
          not($s?name instance of xs:string) or string-length($s?name) lt 1 or string-length($s?name) gt 128 or
          not($s?op=('count','sum','average','min','max')) or ($s?op ne 'count' and not(map:contains($s,'path')))) then md:fail('Invalid aggregate metric')
        else map{'name':$s?name,'op':$s?op,'hasPath':map:contains($s,'path'),'parts':if (map:contains($s,'path')) then [md:parts($s?path)] else []})}
      return if (count(distinct-values(for $i in 1 to array:size($specs) return $specs($i)?name)) ne array:size($specs)) then md:fail('Duplicate metric names') else $specs)""")
    function('metric-value', 'rows positions spec', """let $v := if ($spec?hasPath) then (for $i in $positions return md:get($rows($i),$spec?parts?*)?value) else () return
      if ($spec?op='count') then (if ($spec?hasPath) then count($v) else count($positions))
      else if (some $n in $v satisfies not($n instance of xs:numeric)) then md:fail('Numeric aggregate requires numbers; convert text explicitly')
      else if ($spec?op=('sum','average') and (some $n in $v satisfies string-length(replace(string(abs($n)),'[^0-9]','')) gt 1000)) then md:fail('Aggregate integer exceeds 1000 digits')
      else if ($spec?op='sum') then sum($v,0) else if (empty($v)) then () else if ($spec?op='average') then avg($v)
      else if ($spec?op='min') then min($v) else max($v)""")
    function('aggregate', 'records keys metrics', """let $r := md:object-rows($records), $m := md:metric-specs($metrics), $index := md:strict-index($r,$keys,false()) return
      if (array:size($m) lt 1) then md:fail('Missing aggregate metrics') else
      md:check(fold-left(1 to array:size($r),map{'rows':[],'bytes':2},function($s,$i){
      let $k := md:key($r($i),$keys), $positions := $index($k) return if ($positions[1] ne $i) then $s else
        md:record-emit($s,'rows',map{'key':md:record-key-values($r($i),$keys),'count':count($positions),
          'values':map:merge(for $j in 1 to array:size($m) return map:entry($m($j)?name,md:metric-value($r,$positions,$m($j))))})})?rows)""")


def literal(value):
    text = json.dumps(value, ensure_ascii=True, allow_nan=False)
    return "parse-json('" + text.replace("'", "''") + "', map{'number-parser':md:number#1})"
