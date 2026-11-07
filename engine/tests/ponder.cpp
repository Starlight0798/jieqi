#include "search.h"

#include <cstdlib>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

using namespace jq;

namespace {
void require(bool ok, const char* message) {
    if (!ok) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}

Position position(std::initializer_list<std::pair<const char*, char>> pieces, const char* pools) {
    std::string board(90, '.');
    for (const auto& [square, piece] : pieces)
        board[make_sq(square[0] - 'a', square[1] - '0')] = piece;
    std::string fen;
    for (int rank = 9; rank >= 0; --rank) {
        int empty = 0;
        for (int file = 0; file < 9; ++file) {
            char p = board[make_sq(file, rank)];
            if (p == '.') { ++empty; continue; }
            if (empty) { fen += char('0' + empty); empty = 0; }
            fen += p;
        }
        if (empty) fen += char('0' + empty);
        if (rank) fen += '/';
    }
    fen += std::string(" w ") + pools + " 0 1";
    Position p;
    std::string error;
    require(p.set_fen(fen, &error), error.c_str());
    return p;
}

Move prediction(const Position& p, const char* own, const char* opponent) {
    SearchResult r;
    r.best = parse_move_coords(own);
    r.pv = {r.best, parse_move_coords(opponent)};
    return ponder_reply(p, r);
}
}

int main() {
    const auto known = position({{"e0", 'K'}, {"e9", 'k'}, {"e5", 'P'}, {"a0", 'R'}, {"a9", 'r'}}, "-");
    require(prediction(known, "a0a1", "a9b9") == parse_move_coords("a9b9"), "face-up reply");
    require(prediction(known, "a0a1", "a9b8") == MOVE_NONE, "illegal reply rejected");
    SearchResult missing;
    require(ponder_reply(known, missing) == MOVE_NONE, "missing PV rejected");
    missing.best = parse_move_coords("a0a1");
    missing.pv = {parse_move_coords("a0a2"), parse_move_coords("a9b9")};
    require(ponder_reply(known, missing) == MOVE_NONE, "mismatched PV rejected");

    auto dark = position({{"e0", 'K'}, {"e9", 'k'}, {"e5", 'P'}, {"a0", 'R'}, {"a9", 'x'}}, "r2");
    require(dark.sole_identity(BLACK) == ROOK, "several copies of one identity are deterministic");
    require(reveal_of(prediction(dark, "a0a1", "a9b9")) == ROOK, "singleton opponent reveal inferred");
    dark.urn[BLACK][type_slot(SOLDIER)] = 1;
    require(dark.sole_identity(BLACK) == NO_TYPE, "multiple identities are uncertain");
    require(prediction(dark, "a0a1", "a9b9") == MOVE_NONE, "ambiguous opponent reveal rejected");

    auto ownDark = position({{"e0", 'K'}, {"e9", 'k'}, {"e5", 'P'}, {"a0", 'X'}, {"a9", 'r'}}, "R2");
    require(prediction(ownDark, "a0a1", "a9b9") != MOVE_NONE, "singleton own reveal allowed");
    Limits limits;
    limits.depth = 3;
    limits.searchMoves = {parse_move_coords("a0a1")};
    Searcher searcher;
    auto result = searcher.go(ownDark, limits, [](const std::string&) {});
    require(result.pv.size() >= 2, "PV continues through a deterministic dark move");
    ownDark = position({{"e0", 'K'}, {"e9", 'k'}, {"e5", 'P'}, {"a0", 'X'}, {"a9", 'r'}}, "R1P1");
    require(prediction(ownDark, "a0a1", "a9b9") == MOVE_NONE, "ambiguous own reveal rejected");
    searcher.clear();
    result = searcher.go(ownDark, limits, [](const std::string&) {});
    require(result.pv.size() == 1, "PV stops at an ambiguous dark move");

    auto capture = position({{"e0", 'K'}, {"e9", 'k'}, {"e5", 'P'}, {"a0", 'R'}, {"a9", 'x'}}, "r1p1");
    require(prediction(capture, "a0a9", "e9e8") == MOVE_NONE, "own capture with unknown observation rejected");
    capture = position({{"e0", 'K'}, {"e9", 'k'}, {"e5", 'P'}, {"a0", 'R'}, {"a9", 'x'}}, "r2");
    require(prediction(capture, "a0a9", "e9e8") != MOVE_NONE, "own capture with known observation allowed");
    capture = position({{"e0", 'K'}, {"e9", 'k'}, {"e5", 'P'}, {"b0", 'R'}, {"a0", 'X'}, {"a9", 'r'}}, "R1P1");
    require(prediction(capture, "b0b1", "a9a0") != MOVE_NONE, "opponent capture of our dark piece reveals nothing to us");
    // Hit at a reported node count: the next NodesTime budget must start there.
    for (const Param& param : params())
        if (std::string(param.name) == "NodesTime") *param.value = 100;
    Position start;
    require(start.set_fen(START_FEN), "start position");
    limits = Limits{};
    limits.ponder = true;
    limits.movetime = 20;
    uint64_t hitNodes = 0;
    searcher.clear();
    result = searcher.go(start, limits, [&](const std::string& info) {
        const auto at = info.find(" nodes ");
        if (at == std::string::npos || hitNodes) return;
        const auto nodes = std::stoull(info.substr(at + 7));
        if (nodes < 5000) return;
        hitNodes = nodes;
        searcher.ponderhit();
    });
    require(hitNodes >= 5000, "NodesTime ponder ignores the pre-hit clock");
    require(result.nodes >= hitNodes + 1000, "NodesTime charges only nodes searched after hit");
    std::cout << "ponder policy and PV checks passed\n";
}
