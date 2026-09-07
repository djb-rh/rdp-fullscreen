// Standalone disassembler for the RDP side-pod work: 68010 (byte-addressed,
// big-endian) and TMS34010 (bit-addressed, little-endian), reusing MAME's
// own disassembler cores so the output matches the debugger exactly.
#include "osdcomm.h"
#include "coretmpl.h"
using namespace util;
#include "disasmintf.h"
#include "m68kdasm.h"
#include "34010dsm.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <sstream>
#include <vector>

using util::disasm_interface;
typedef disasm_interface::offs_t offs_t;

// 68010: pc is a byte address, data is big-endian.
class be_buffer : public disasm_interface::data_buffer {
public:
	be_buffer(const std::vector<uint8_t> &d, uint32_t base) : m_d(d), m_base(base) {}
	uint8_t at(offs_t p) const { p -= m_base; return p < m_d.size() ? m_d[p] : 0xff; }
	uint8_t  r8 (offs_t pc) const override { return at(pc); }
	uint16_t r16(offs_t pc) const override { return (at(pc) << 8) | at(pc+1); }
	uint32_t r32(offs_t pc) const override { return ((uint32_t)r16(pc) << 16) | r16(pc+2); }
	uint64_t r64(offs_t pc) const override { return ((uint64_t)r32(pc) << 32) | r32(pc+4); }
private:
	const std::vector<uint8_t> &m_d; uint32_t m_base;
};

// TMS34010: pc is a BIT address, data is little-endian 16-bit words.
class gsp_buffer : public disasm_interface::data_buffer {
public:
	gsp_buffer(const std::vector<uint8_t> &d, uint32_t base) : m_d(d), m_base(base) {}
	uint16_t w(offs_t bit) const {
		uint32_t byte = (bit - m_base) >> 3;
		if (byte + 1 >= m_d.size()) return 0xffff;
		return m_d[byte] | (m_d[byte+1] << 8);
	}
	uint8_t  r8 (offs_t pc) const override { return w(pc) & 0xff; }
	uint16_t r16(offs_t pc) const override { return w(pc); }
	uint32_t r32(offs_t pc) const override { return w(pc) | ((uint32_t)w(pc+16) << 16); }
	uint64_t r64(offs_t pc) const override { return r32(pc) | ((uint64_t)r32(pc+32) << 32); }
private:
	const std::vector<uint8_t> &m_d; uint32_t m_base;
};

static std::vector<uint8_t> load(const char *p) {
	FILE *f = fopen(p, "rb");
	if (!f) { fprintf(stderr, "cannot open %s\n", p); exit(1); }
	fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
	std::vector<uint8_t> v(n);
	if (fread(v.data(), 1, n, f) != size_t(n)) { fprintf(stderr, "short read\n"); exit(1); }
	fclose(f); return v;
}

int main(int argc, char **argv) {
	if (argc < 5) {
		fprintf(stderr,
			"usage: dasm <68k|gsp> <file> <base> <start> [len]\n"
			"  68k: base/start/len are BYTE addresses\n"
			"  gsp: base/start/len are BIT addresses (0xffc00000 = start of gsp_vram)\n");
		return 1;
	}
	bool gsp = !strcmp(argv[1], "gsp");
	std::vector<uint8_t> data = load(argv[2]);
	uint32_t base  = strtoul(argv[3], nullptr, 0);
	uint32_t start = strtoul(argv[4], nullptr, 0);
	uint32_t len   = argc > 5 ? strtoul(argv[5], nullptr, 0)
	                          : (gsp ? data.size() * 8 : data.size());

	m68k_disassembler m68(m68k_disassembler::TYPE_68010);
	tms34010_disassembler t34(false);
	disasm_interface &d = gsp ? (disasm_interface &)t34 : (disasm_interface &)m68;

	be_buffer  bb(data, base);
	gsp_buffer gb(data, base);
	const disasm_interface::data_buffer &buf =
		gsp ? (const disasm_interface::data_buffer &)gb
		    : (const disasm_interface::data_buffer &)bb;

	uint32_t pc = start, end = start + len;
	while (pc < end) {
		std::ostringstream s;
		offs_t r = d.disassemble(s, pc, buf, buf);
		uint32_t n = r & disasm_interface::LENGTHMASK;
		if (!n) n = d.opcode_alignment();
		uint32_t step = gsp ? 16 : 2;          // bits per word vs bytes per word
		uint32_t words = n / step; if (!words) words = 1;
		printf("%08X: ", pc);
		for (uint32_t i = 0; i < words; i++)
			printf("%04X ", gsp ? gb.w(pc + i * step) : bb.r16(pc + i * step));
		printf("%*s%s\n", (words < 5) ? int(5 - words) * 5 : 0, "", s.str().c_str());
		pc += words * step;
	}
	return 0;
}
