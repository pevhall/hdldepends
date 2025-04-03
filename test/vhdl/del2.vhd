library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library xpm;
use xpm.vcomponents.all;

use std.textio.all;


entity del2 is
  generic (
    TEST : integer;
    sdf : in  std_logic_vector(32-1 downto 0);
    TESTsdf : integer
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
end entity del;

architecture sim of del2 is
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
  end component delComp;

  signal test_w_ovr : unsigned(3 downto 0);
  alias test_ovr is test_w_ovr(3);
  alias tessdft is test_w_ovr(3-1 downto 0);

  component delComp2 is
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

begin
  assert test_w_ovr = 0 report "test_w_ovr = "&to_hstring(unsigned(test_w_ovr)) severity FAILURE;

process(clk_i)
begin
  if rising_edge(clk_i) then
    if en_i = '1' then
      tessdft  <= (others => '0');
    end if;
  end if;
end process;

  i_del : entity work.del21
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
 
i_xpm_cdc_async_rst : xpm_cdc_async_rst
  generic map(

    -- Common module parameters
    DEST_SYNC_FF    => 4,
    INIT_SYNC_FF    => 0,
    RST_ACTIVE_HIGH => 0
  )
  port map(

    src_arst  => open,
    dest_clk  => open,
    dest_arst => open
  ); 

----- component xpm_cdc_sync_rst -----
component xpm_cdc_sync_rst
  port map(
    src_arst  => open,
    dest_clk  => open,
    dest_arst => open
  );
end architecture;

