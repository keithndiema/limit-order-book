#pragma once
// Tiny test harness. Unlike <cassert>, CHECK is never compiled out by -DNDEBUG,
// so the suite means the same thing in Debug, Release and sanitizer builds.

#include <cstdio>
#include <functional>
#include <string>
#include <vector>

namespace check {

struct Registry {
    std::vector<std::pair<std::string, std::function<void()>>> tests;
    int failures = 0;
    static Registry& get() { static Registry r; return r; }
};

struct Registrar {
    Registrar(const char* name, std::function<void()> fn) { Registry::get().tests.emplace_back(name, std::move(fn)); }
};

inline void fail(const char* file, int line, const char* expr) {
    std::fprintf(stderr, "    CHECK FAILED %s:%d: %s\n", file, line, expr);
    ++Registry::get().failures;
}

inline int run_all() {
    auto& r = Registry::get();
    int failed_tests = 0;
    for (auto& [name, fn] : r.tests) {
        const int before = r.failures;
        fn();
        const bool ok = r.failures == before;
        std::printf("[%s] %s\n", ok ? "PASS" : "FAIL", name.c_str());
        if (!ok) ++failed_tests;
    }
    std::printf("\n%zu tests, %d failed\n", r.tests.size(), failed_tests);
    return failed_tests == 0 ? 0 : 1;
}

}  // namespace check

#define CHECK(expr) do { if (!(expr)) ::check::fail(__FILE__, __LINE__, #expr); } while (0)
#define CHECK_EQ(a, b) do { if (!((a) == (b))) ::check::fail(__FILE__, __LINE__, #a " == " #b); } while (0)
#define TEST_CASE(name) \
    static void name(); \
    static ::check::Registrar reg_##name(#name, name); \
    static void name()
// Run the same body against both implementations.
#define TEST_BOTH(name) \
    template <class Book> static void name##_impl(); \
    static ::check::Registrar reg_##name##_fast(#name " [OrderBook]", name##_impl<lob::OrderBook>); \
    static ::check::Registrar reg_##name##_ref(#name " [ReferenceBook]", name##_impl<lob::ReferenceBook>); \
    template <class Book> static void name##_impl()
