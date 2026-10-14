module axis_data_to_chdr
import misc_package::*;
# (
  parameter int CNTR_W
)  (
cntr_o      ,  // Output of the counter
up_down_i  ,  // up_down_i control for counter
clk_i      ,  // clock input
rst_i       // rst_i input
);
output [CNTR_W-1:0] cntr_o;
//------------Input Ports-------------- 
input [7:0] data;
input up_down_i, clk_i, rst_i;

IOBUF scl_iobuf_1
(
	.O(scl_i),
.IO(scl),
.I(scl_o),
.T(scl_t)
);

endmodule 
