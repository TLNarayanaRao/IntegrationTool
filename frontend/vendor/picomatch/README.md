# MINA picomatch security backport

This private build dependency is based on upstream picomatch 4.0.7.
The upstream MIT license is in this directory. The original npm tarball
has the SHA-512 integrity recorded below.

```
sha512-qcJu88Q2IWqJsDD529JKMdwGm/dvInW4HvQnRwiH9JtihJvzGOscDtHE3x1pBKeUOTysQ8kVmLnJ2kJu7yhcGA==
```

The change in `lib/parse.js` routes complex repeated glob alternatives
through the parser's existing literal-matching path. It preserves the
existing safe character-class rewrites and repetition of simple,
unescaped literal alternatives with distinct prefixes. This check also runs when a caller
disables the older recursion limit.

npm installs the patched fork under the `picomatch` import name for
every consumer in the Studio build dependency tree. Its manifest and
lockfile record the local source and fork version.

Track the upstream advisory when updating this dependency.
[Source release](https://github.com/micromatch/picomatch/releases/tag/4.0.7) ·
[Security advisory](https://github.com/advisories/GHSA-fc5q-39xc-vjpf)
