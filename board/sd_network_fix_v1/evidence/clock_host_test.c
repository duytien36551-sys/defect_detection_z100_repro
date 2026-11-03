
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
typedef uint32_t u32_t; typedef uintptr_t UINTPTR;
static uint32_t pll,clk,locked,status;static int writes,fail_write;
static uint32_t Xil_In32(uintptr_t a){switch(a){case 0xf8000108U:return pll;case 0xf8000140U:return clk;case 0xf800000cU:return locked;case 0xf800010cU:return status;default:assert(0);return 0;}}
static void Xil_Out32(uintptr_t a,uint32_t v){++writes;switch(a){case 0xf8000140U:if(!fail_write)clk=v;break;case 0xf8000008U:assert(v==0xdf0dU);locked=0;break;case 0xf8000004U:assert(v==0x767bU);locked=1;break;default:assert(0);}}
static void init(void){pll=0x1e008;clk=0x100801;locked=1;status=0x3f;writes=0;fail_write=0;}
static int z100_sdt_gem0_clock(u32_t speed)
{
    const UINTPTR ctrl = (UINTPTR)0xf8000140U;
    u32_t pll = Xil_In32((UINTPTR)0xf8000108U);
    u32_t old = Xil_In32(ctrl), value, div0, div1, locked;
    if ((pll & 0x0007f013U) != 0x0001e000U ||
        !(Xil_In32((UINTPTR)0xf800010cU) & 4U) ||
        (old & 0x70U) || !(old & 1U)) return 0;
    if (speed == 1000U) { div0 = 8U; div1 = 1U; }
    else if (speed == 100U) { div0 = 40U; div1 = 1U; }
    else if (speed == 10U) { div0 = 40U; div1 = 10U; }
    else return 0;
    value = (old & ~0x03f03f00U) | (div0 << 8) | (div1 << 20);
    if (value == old) return 1;
    locked = Xil_In32((UINTPTR)0xf800000cU) & 1U;
    if (locked) Xil_Out32((UINTPTR)0xf8000008U, 0xdf0dU);
    Xil_Out32(ctrl, value);
    /* MMIO barrier mocked for host. */
    if (Xil_In32(ctrl) != value) {
        Xil_Out32(ctrl, old);
        /* MMIO barrier mocked for host. */
        if (locked) Xil_Out32((UINTPTR)0xf8000004U, 0x767bU);
        return 0;
    }
    if (locked) Xil_Out32((UINTPTR)0xf8000004U, 0x767bU);
    return 1;
}
int main(void){
init();assert(z100_sdt_gem0_clock(100));assert(clk==0x102801&&locked==1&&writes==3);
init();assert(z100_sdt_gem0_clock(1000));assert(clk==0x100801&&writes==0);
init();assert(z100_sdt_gem0_clock(10));assert(clk==0xa02801&&locked==1);
init();locked=0;assert(z100_sdt_gem0_clock(100));assert(!locked&&writes==1);
init();pll=0x1d008;assert(!z100_sdt_gem0_clock(100)&&writes==0);
init();pll|=0x10;assert(!z100_sdt_gem0_clock(100)&&writes==0);
init();pll|=1;assert(!z100_sdt_gem0_clock(100)&&writes==0);
init();status&=~4U;assert(!z100_sdt_gem0_clock(100)&&writes==0);
init();clk|=0x10;assert(!z100_sdt_gem0_clock(100)&&writes==0);
init();clk&=~1U;assert(!z100_sdt_gem0_clock(100)&&writes==0);
init();assert(!z100_sdt_gem0_clock(123)&&writes==0);
init();fail_write=1;assert(!z100_sdt_gem0_clock(100));assert(clk==0x100801&&locked==1);
puts("CLOCK_HOST_12_CASES_PASS");return 0;}
