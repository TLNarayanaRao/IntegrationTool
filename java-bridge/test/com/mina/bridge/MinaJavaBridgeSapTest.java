package com.mina.bridge;

import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

public final class MinaJavaBridgeSapTest {
    public static void main(String[] args) throws Exception {
        int count = args.length == 0 ? 100 : Integer.parseInt(args[0]);
        Path directory = Files.createTempDirectory("mina-sap-test-");
        try {
            Path legacy = directory.resolve("tid.properties");
            Files.writeString(legacy, "old=COMMITTED\ninterrupted=RECEIVED\n");
            MinaJavaBridge.SapTidStore store = new MinaJavaBridge.SapTidStore(legacy);
            require(!store.check("old"), "Legacy committed transaction can replay");
            require(store.check("interrupted") && !store.check("interrupted"), "An interrupted transaction must be retried once");
            store.rollback("interrupted");
            require(store.check("interrupted"), "Rolled back transaction could not retry");
            store.commit("interrupted");
            store = new MinaJavaBridge.SapTidStore(legacy);
            require(!store.check("interrupted"), "Committed transaction lost after restart");
            store.confirm("interrupted");
            store.confirm("old");
            store = new MinaJavaBridge.SapTidStore(legacy);
            require(store.check("old") && store.check("interrupted"), "Confirmed TIDs were not cleared");

            Method split = MinaJavaBridge.class.getDeclaredMethod("splitIdocPackage", Map.class);
            split.setAccessible(true);
            List<Map<String, String>> controlOnly = List.of(Map.of("DOCNUM", "1"), Map.of("DOCNUM", "2"));
            require(((List<?>) split.invoke(null, Map.of("tables", Map.of("IDOC_CONTROL_REC_40", controlOnly)))).size() == 2,
                    "A package without a segment table lost a control record");
            expectBadPackage(split, List.of(Map.of("DOCNUM", "1"), "invalid row"), List.of());
            expectBadPackage(split, controlOnly, List.of(Map.of("DOCNUM", "3")));
            expectBadPackage(split, List.of(Map.of("DOCNUM", "1"), Map.of("DOCNUM", "1")), List.of());
            long begin = System.nanoTime();
            for (int first = 0; first < count; first += 250) {
                int size = Math.min(count - first, 250);
                List<Map<String, String>> controls = new ArrayList<>(), segments = new ArrayList<>();
                for (int index = first; index < first + size; index++) {
                    String number = Integer.toString(index);
                    controls.add(Map.of("DOCNUM", number));
                    segments.add(Map.of("DOCNUM", number, "SDATA", "one"));
                }
                for (int index = first + size - 1; index >= first; index--) {
                    segments.add(Map.of("DOCNUM", Integer.toString(index), "SDATA", "two"));
                }
                List<?> result = (List<?>) split.invoke(null, Map.of("tables", Map.of("IDOC_CONTROL_REC_40", controls, "IDOC_DATA_REC_40", segments)));
                require(result.size() == size, "Unexpected IDoc count");
                for (int index = 0; index < size; index++) {
                    Map<?, ?> tables = (Map<?, ?>) ((Map<?, ?>) result.get(index)).get("tables");
                    String number = Integer.toString(first + index);
                    require(List.of(Map.of("DOCNUM", number, "SDATA", "one"), Map.of("DOCNUM", number, "SDATA", "two")).equals(tables.get("IDOC_DATA_REC_40")), "Segment cross-contamination or reordering");
                    require(store.check(number), "Unexpected duplicate TID");
                    store.commit(number);
                    require(!store.check(number), "Committed TID was accepted twice");
                    store.confirm(number);
                }
            }
            System.out.printf("Verified %,d synthetic IDocs and TID cycles in %.3f seconds%n", count, (System.nanoTime() - begin) / 1e9);
        } finally {
            try (var files = Files.walk(directory)) {
                for (Path path : files.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
            }
        }
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void expectBadPackage(Method split, List<?> controls, List<?> segments) throws Exception {
        try {
            split.invoke(null, Map.of("tables", Map.of("IDOC_CONTROL_REC_40", controls, "IDOC_DATA_REC_40", segments)));
            throw new AssertionError("An invalid IDoc package was accepted");
        } catch (java.lang.reflect.InvocationTargetException error) {
            require(error.getCause() instanceof IllegalArgumentException, "Invalid package raised an unexpected error");
        }
    }
}
