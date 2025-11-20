library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use std.textio.all;

library unisim;
use unisim.vcomponents.all;

use work.del_pkg.all;

entity del is
  generic (
    TEST : integer;
    sdf : in  std_logic_vector(32-1 downto 0);
    TESTsdf : integer
  );
  port (
    clk_i    : in  std_logic;
    en_i     : in  std_logic; 
    testa_i  : in  std_logic;
    testdb_i : in  std_logic;
    tesdt_i  : in  std_logic;
    sdf_i    : in  std_logic_vector(32-1 downto 0);
    tedast_i : out  std_logic

  );
end del;

architecture sim of del is
  constant PATH : string := "";

  component delComp is
    generic (
      TEST : integer;
      DSF : in  std_logic_vector(32-1 downto 0)
    );
    port (
      clk_i : in  std_logic;
      en_i : in  std_logic; --(((
      testa_i : in  std_logic;
      testdb_i : in  std_logic;
      tesdt_i : in  std_logic;
      sdf_i : in  std_logic_vector(32-1 downto 0);
      tedast_i : out  std_logic

    );
  end component;

  signal test_w_ovr : unsigned(3 downto 0);
  alias test_ovr is test_w_ovr(3);
  alias tessdft is test_w_ovr(3-1 downto 0);

  component dynamic_bram_loading_axi_controller_xci is
   port (
     clk_i : in  std_logic;
     en_i : in  std_logic; --(((
     src_i : in  std_logic;
     dst_o : out  std_logic

   );
  end component;

-- COMPONENT axi_bram_ctrl_0
--   PORT (
--     s_axi_aclk : IN STD_LOGIC;
--     s_axi_aresetn : IN STD_LOGIC;
--     s_axi_awaddr : IN STD_LOGIC_VECTOR(11 DOWNTO 0);
--     s_axi_awlen : IN STD_LOGIC_VECTOR(7 DOWNTO 0);
--     s_axi_awsize : IN STD_LOGIC_VECTOR(2 DOWNTO 0);
--     s_axi_awburst : IN STD_LOGIC_VECTOR(1 DOWNTO 0);
--     s_axi_awlock : IN STD_LOGIC;
--     s_axi_awcache : IN STD_LOGIC_VECTOR(3 DOWNTO 0);
--     s_axi_awprot : IN STD_LOGIC_VECTOR(2 DOWNTO 0);
--     s_axi_awvalid : IN STD_LOGIC;
--     s_axi_awready : OUT STD_LOGIC;
--     s_axi_wdata : IN STD_LOGIC_VECTOR(31 DOWNTO 0);
--     s_axi_wstrb : IN STD_LOGIC_VECTOR(3 DOWNTO 0);
--     s_axi_wlast : IN STD_LOGIC;
--     s_axi_wvalid : IN STD_LOGIC;
--     s_axi_wready : OUT STD_LOGIC;
--     s_axi_bresp : OUT STD_LOGIC_VECTOR(1 DOWNTO 0);
--     s_axi_bvalid : OUT STD_LOGIC;
--     s_axi_bready : IN STD_LOGIC;
--     s_axi_araddr : IN STD_LOGIC_VECTOR(11 DOWNTO 0);
--     s_axi_arlen : IN STD_LOGIC_VECTOR(7 DOWNTO 0);
--     s_axi_arsize : IN STD_LOGIC_VECTOR(2 DOWNTO 0);
--     s_axi_arburst : IN STD_LOGIC_VECTOR(1 DOWNTO 0);
--     s_axi_arlock : IN STD_LOGIC;
--     s_axi_arcache : IN STD_LOGIC_VECTOR(3 DOWNTO 0);
--     s_axi_arprot : IN STD_LOGIC_VECTOR(2 DOWNTO 0);
--     s_axi_arvalid : IN STD_LOGIC;
--     s_axi_arready : OUT STD_LOGIC;
--     s_axi_rdata : OUT STD_LOGIC_VECTOR(31 DOWNTO 0);
--     s_axi_rresp : OUT STD_LOGIC_VECTOR(1 DOWNTO 0);
--     s_axi_rlast : OUT STD_LOGIC;
--     s_axi_rvalid : OUT STD_LOGIC;
--     s_axi_rready : IN STD_LOGIC;
--     bram_rst_a : OUT STD_LOGIC;
--     bram_clk_a : OUT STD_LOGIC;
--     bram_en_a : OUT STD_LOGIC;
--     bram_we_a : OUT STD_LOGIC_VECTOR(3 DOWNTO 0);
--     bram_addr_a : OUT STD_LOGIC_VECTOR(11 DOWNTO 0);
--     bram_wrdata_a : OUT STD_LOGIC_VECTOR(31 DOWNTO 0);
--     bram_rddata_a : IN STD_LOGIC_VECTOR(31 DOWNTO 0) 
--   );
-- END COMPONENT;

     -- Component declaration for led_controller
    component led_controller is
      Port (
        clk     : in  STD_LOGIC;
        btn     : in  STD_LOGIC_VECTOR(1 downto 0);
        led     : out STD_LOGIC_VECTOR(3 downto 0)
      );
    end component;

  

begin
  assert test_w_ovr = 0 report "test_w_ovr = "&to_hstring(unsigned(test_w_ovr)) severity FAILURE;

process(clk_i)
begin
  if rising_edge(clk_i) then
    if en_i = '1' then
      while true loop
        tessdft  <= (others => '0');
      end loop;
    end if;
  end if;
end process;

  i_dynamic_bram_loading_axi_controller_xci: dynamic_bram_loading_axi_controller_xci
   port map(
     clk_i => clk_i,
     en_i => en_i,
     src_i => '0',
     dst_o => open
   );


  i_del : delComp
  generic map (
    TEST     => TEST,
    sdf      => sdf,
    TESTsdf  => TESTsdf
  )
  port map (
    clk_i    => clk_i,
    en_i     => en_i,
    testa_i  => testa_i,
    testdb_i => testdb_i,
    tesdt_i  => tesdt_i,
    sdf_i    => sdf_i,
    tedast_i => tedast_i
  );

  i_del2 : entity work.del2(rtl)
  generic map (
    TEST     => TEST,
    sdf      => sdf,
    TESTsdf  => TESTsdf
  )
  port map (
    clk_i    => clk_i,
    en_i     => en_i,
    testa_i  => testa_i,
    testdb_i => testdb_i,
    tesdt_i  => tesdt_i,
    sdf_i    => sdf_i,
    tedast_i => tedast_i
  );

  i_del3 : entity work.del3
  generic map (
    TEST     => TEST,
    TESTsdf  => TESTsdf
  )
  port map (
    clk_i    => clk_i,
    sdf_i    => sdf_i,
    tedast_i => tedast_i
  );

  led_ctrl_inst: led_controller
  port map (
    clk => clk,
    btn => btn,
    led => led
  );

  your_instance_name : entity work.axi_bram_ctrl_0
  PORT MAP (
    s_axi_aclk => s_axi_aclk,
    s_axi_aresetn => s_axi_aresetn,
    s_axi_awaddr => s_axi_awaddr,
    s_axi_awlen => s_axi_awlen,
    s_axi_awsize => s_axi_awsize,
    s_axi_awburst => s_axi_awburst,
    s_axi_awlock => s_axi_awlock,
    s_axi_awcache => s_axi_awcache,
    s_axi_awprot => s_axi_awprot,
    s_axi_awvalid => s_axi_awvalid,
    s_axi_awready => s_axi_awready,
    s_axi_wdata => s_axi_wdata,
    s_axi_wstrb => s_axi_wstrb,
    s_axi_wlast => s_axi_wlast,
    s_axi_wvalid => s_axi_wvalid,
    s_axi_wready => s_axi_wready,
    s_axi_bresp => s_axi_bresp,
    s_axi_bvalid => s_axi_bvalid,
    s_axi_bready => s_axi_bready,
    s_axi_araddr => s_axi_araddr,
    s_axi_arlen => s_axi_arlen,
    s_axi_arsize => s_axi_arsize,
    s_axi_arburst => s_axi_arburst,
    s_axi_arlock => s_axi_arlock,
    s_axi_arcache => s_axi_arcache,
    s_axi_arprot => s_axi_arprot,
    s_axi_arvalid => s_axi_arvalid,
    s_axi_arready => s_axi_arready,
    s_axi_rdata => s_axi_rdata,
    s_axi_rresp => s_axi_rresp,
    s_axi_rlast => s_axi_rlast,
    s_axi_rvalid => s_axi_rvalid,
    s_axi_rready => s_axi_rready,
    bram_rst_a => bram_rst_a,
    bram_clk_a => bram_clk_a,
    bram_en_a => bram_en_a,
    bram_we_a => bram_we_a,
    bram_addr_a => bram_addr_a,
    bram_wrdata_a => bram_wrdata_a,
    bram_rddata_a => bram_rddata_a
  );

your_instance_name : fir_compiler_0
  PORT MAP (
    aclk => aclk,
    s_axis_data_tvalid => s_axis_data_tvalid,
    s_axis_data_tready => s_axis_data_tready,
    s_axis_data_tdata => s_axis_data_tdata,
    m_axis_data_tvalid => m_axis_data_tvalid,
    m_axis_data_tdata => m_axis_data_tdata
  );

  your_instance_name : entity work.fir_compiler_0_sim
  PORT MAP (
    aclk => aclk,
    s_axis_data_tvalid => s_axis_data_tvalid,
    s_axis_data_tready => s_axis_data_tready,
    s_axis_data_tdata => s_axis_data_tdata,
    m_axis_data_tvalid => m_axis_data_tvalid,
    m_axis_data_tdata => m_axis_data_tdata
  );

end architecture;

