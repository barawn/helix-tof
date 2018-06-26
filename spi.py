import struct
import sys
import time
import hexfile
from bf import * 

#Low-level implementations.
# OpenCores SPI controller. Typically on an OpenCores PCI device, so
# usually just has read/write
class OCSPI:
	map = { 'SPCR'       : 0x000000,
            'SPSR'       : 0x000004,
            'SPDR'       : 0x000008,
            'SPER'       : 0x00000C }

	bits = { 'SPIF'      : 0x80,
             'WCOL'      : 0x40,
             'WFFULL'    : 0x08,
             'WFEMPTY'   : 0x04,
             'RFFULL'    : 0x02,
             'RFEMPTY'   : 0x01 }

	def __init__(self, dev, base, device=0):
		self.dev = dev
		self.base = base
		self.device = device
		val = bf(self.dev.read(self.base + self.map['SPCR']))
		val[6] = 1
		val[3] = 0
		val[2] = 0
		self.dev.write(self.base+self.map['SPCR'], int(val))
		
	def command(self, command, dummy_bytes, num_read_bytes, data_in = []):
		self.dev.spi_cs(self.device, 1)
		self.dev.write(self.base + self.map['SPDR'], command)
		x = 0 
		for dat in data_in:
			self.dev.write(self.base + self.map['SPDR'], dat)
			val = bf(self.dev.read(self.map['SPSR']))
			x+=1
			if val[6] == 1:
				return x 
		for i in range(dummy_bytes):
			self.dev.write(self.base + self.map['SPDR'], 0x00)
		# Empty the read FIFO.
		while not (self.dev.read(self.base + self.map['SPSR']) & self.bits['RFEMPTY']):
			self.dev.read(self.base + self.map['SPDR'])
		rdata = []
		for i in range(num_read_bytes):
			self.dev.write(self.base + self.map['SPDR'], 0x00)
			rdata.append(self.dev.read(self.base + self.map['SPDR']))
		self.dev.spi_cs(self.device, 0)    
		return rdata


# Xilinx AXI Quad SPI controller. This one presumes you have
# a read/write/readMultiple command.
# (I should implement readMultiple for the OpenCores PCI device...)
class AXIQuadSPI:
	map = { 'SRR'				: 0x40,
			'SPICR'				: 0x60,
			'SPISR'				: 0x64,
			'SPIDTR'			: 0x68,
			'SPIDRR'			: 0x6C,
			'SPISSR'			: 0x70,
			'SPITXFIFOAVAIL'	: 0x74,
			'SPIRXFIFOAVAIL'	: 0x78,
			'DGIER'				: 0x1C,
			'IPISR'				: 0x20,
			'IPIER'				: 0x28 }
	def __init__(self, dev, base, device=0):
		self.dev = dev
		self.base = base
		self.device = device
		# Don't need to initialize anything in this case.

	def command(self, command, dummy_bytes, num_read_bytes, data_in = []):
		# reset RX/TX FIFOs + master transaction inhibit + slave assertion + spi enable + master mode		
		self.dev.write(self.base+self.map['SPICR'], 0x1E6)
		# compose the full data to be sent
		# that is, the RES command, which sends
		# 
		data = [ command ] + data_in + [0]*(dummy_bytes + num_read_bytes)
		rdata = []
		# short operation?
		if len(data) <= 16:
			self.dev.write(self.base+self.map['SPIDTR'], data)
			val = bf(0xFFFF)
			val[self.device]=0			
			self.dev.write(self.base+self.map['SPISSR'], int(val))
			# enable transaction (+no reset)
			self.dev.write(self.base+self.map['SPICR'], 0x86)
			ntries=0
			while ntries<1000:
				ntries=ntries+1
				if (self.dev.read(self.base+self.map['SPISR']) & 0x4):
					break
			rdata=self.dev.readMultiple(self.base+self.map['SPIDRR'], len(data))
		else:
			# yoink 16 bytes of data
			count=len(data)
			wdata=data[0:16]
			data=data[16:]
			rdata=[]
			self.dev.write(self.base+self.map['SPIDTR'], wdata)
			val = bf(0xFFFF)
			val[self.device]=0			
			self.dev.write(self.base+self.map['SPISSR'], int(val))
			self.dev.write(self.base+self.map['SPICR'], 0x86)
			# now loop
			while True:
				ntries=0
				while ntries<1000:
					ntries=ntries+1
					if (self.dev.read(self.base+self.map['SPISR']) & 0x4):
						break
				rdata.extend(self.dev.readMultiple(self.base+self.map['SPIDRR'], len(wdata)))
				count = count - len(wdata)
				if count == 0:
					break
				if len(data) <= 16:
					wdata=data
				else:
					wdata=data[0:16]
					data=data[16:]
				
				self.dev.write(self.base+self.map['SPIDTR'], wdata)
		self.dev.write(self.base+self.map['SPISSR'], 0xFFFF)
		self.dev.write(self.base+self.map['SPICR'], 0x186)
		# Strip off command, dummy bytes, and write data (then back one since we start at 0)
		rdata=rdata[1+dummy_bytes+len(data_in):]
		return rdata

class SPI:    
	cmd = { 'RES'        : 0xAB ,
            'RDID'       : 0x9F ,
            'WREN'       : 0x06 ,
            'WRDI'       : 0x04 ,
            'RDSR'       : 0x05 ,
            'WRSR'       : 0x01 ,
            '4READ'      : 0x13 , 
		    '3READ'      : 0x03 ,   
            'FASTREAD'   : 0x0B ,
            '4PP'        : 0x12 , 
		    '3PP'        : 0x02 , 
            '4SE'        : 0xDC , 
            '3SE'        : 0xD8 ,
            'BRRD'       : 0x16 , 
            'BRWR'       : 0x17 , 
            'BE'         : 0xC7 ,
			'RDSFDP'	 : 0x5A }
			    
	def command(self, command, dummy_bytes, num_read_bytes, data_in = []):
		return self.dev.command(command, dummy_bytes, num_read_bytes, data_in)
		
	def __init__(self, low_level_spi):
		self.dev = low_level_spi
		res = self.command(self.cmd['RES'], 3, 1)
		self.electronic_signature = res[0]
		res = self.command(self.cmd['RDID'], 0, 4)
		self.manufacturer_id = res[0]
		self.memory_type = res[1]
		self.memory_capacity = 2**res[2]        
		extended_data_count = res[3]
		self.extended_data = []
		if extended_data_count != 0 and extended_data_count != 255:
			res = self.command(self.cmd['RDID'], 0, 4+extended_data_count)
			self.extended_data = res[4:]
        # Now try fetching SFDP.
		self.serial_flash_parameters = []
		addr=[0,0,0]
		res = self.command(self.cmd['RDSFDP'], 1, 16, addr)
		if chr(res[0]) == 'S' and chr(res[1]) == 'F' and chr(res[2]) == 'D' and chr(res[3]) == 'P':
			# OK, it supports SFDP.
			if res[8] == 0:
				# parameter ID 0
				len=res[11]*4
				# grr. read out = lowest address first
				# send in = highest address first
				addr=[ res[14], res[13], res[12] ]
				self.serial_flash_parameters = self.command(self.cmd['RDSFDP'], 1, len, addr)
		
		
	def status(self):
		res = self.command(self.cmd['RDSR'], 0, 1)
		return res[0]    

	def identify(self):
		print "Electronic Signature: 0x%x" % self.electronic_signature
		print "Manufacturer ID: 0x%x" % self.manufacturer_id
		print "Memory Type: 0x%x Memory Capacity: %d bytes" % (self.memory_type, self.memory_capacity)
		if len(self.extended_data):
			print "Extended Data:"
			i = 0
			while i<len(self.extended_data):
				dat=self.extended_data[i:i+16]
				print '[{}]'.format(', '.join(hex(x) for x in dat))
				i=i+16
		if len(self.serial_flash_parameters):
			print "Serial Flash Discoverable Parameters:"
			i = 0
			while i<len(self.serial_flash_parameters):
				dat=self.serial_flash_parameters[i:i+16]
				print '[{}]'.format(', '.join(hex(x) for x in dat))
				i=i+16
							
	def read(self, address, length):
		if self.memory_capacity > 2**24:
			data_in = []
			data_in.append((address >> 24) & 0xFF)
			data_in.append((address >> 16) & 0xFF)
			data_in.append((address >> 8) & 0xFF)
			data_in.append(address & 0xFF)
			result = self.command(self.cmd['4READ'], 0, length, data_in)
		else:
			data_in = []
			data_in.append((address >> 16) & 0xFF)
			data_in.append((address >> 8) & 0xFF)
			data_in.append(address & 0xFF)
			result = self.command(self.cmd['3READ'], 0, length, data_in)
		return result 
	
	def write_enable(self):
		enable = self.command(self.cmd["WREN"], 0, 0)
		trials = 0
		while trials < 10:
			res = self.status()
			if not res & 0x2:
				trials = trials + 1
			else:
				return
		print "Write enable failed (%d)!" % res
		
	def write_disable(self):
		disable = self.command(self.cmd["WRDI"], 0, 0)
		res = self.status()
		if res & 0x2:
			print "Write disable failed (%d)!" % res

	def find_erase_sector_size(self):
		sector_size = 0
		if len(self.serial_flash_parameters) != 0:
			# derive sector size from parameters
			print "Finding sector size from SFDP"
			if self.serial_flash_parameters[0x1D] == self.cmd['3SE']:
				sector_size=2**self.serial_flash_parameters[0x1C]
			elif self.serial_flash_parameters[0x1F] == self.cmd['3SE']:
				sector_size=2**self.serial_flash_parameters[0x1E]
			elif self.serial_flash_parameters[0x21] == self.cmd['3SE']:
				sector_size=2**self.serial_flash_parameters[0x20]
			elif self.serial_flash_parameters[0x23] == self.cmd['3SE']:
				sector_size=2**self.serial_flash_parameters[0x22]
		else:
			if self.manufacturer_id == 0x01 and len(self.extended_data) != 0:
				print "Finding sector size from Spansion/Cypress CFI"
				if self.extended_data[0] == 0x00:
					sector_size = 256*1024
				elif self.extended_data[0] == 0x01:
					sector_size = 64*1024
				else:
					print "Unknown sector architecture %x in Spansion/Cypress CFI" % self.extended_data[0]
					print "Guessing 64 kB."
					sector_size = 64*1024
			else:
				print "No SFDP, no CFI: guessing sector size is 64 kB"
				print "If this is wrong, try passing the correct value"
				sector_size = 64*1024
		return sector_size	

	@staticmethod
	def update_progress(progress):
		barLength = 10 # Modify this to change the length of the progress bar
		status = ""
		if isinstance(progress, int):
			progress = float(progress)
		if not isinstance(progress, float):
			progress = 0
			status = "error: progress var must be float\r\n"
		if progress < 0:
			progress = 0
			status = "Halt...\r\n"
		if progress >= 1:
			progress = 1
			status = "Done...\r\n"
		block = int(round(barLength*progress))
		text = "\rPercent: [%s] %.2f %s" % ("#"*block + "-"*(barLength-block), progress*100, status)
		sys.stdout.write(text)
		sys.stdout.flush()


	def program_mcs(self, filename, sector_size=0):
		f = hexfile.load(filename)
		# Figure out what sectors we need to erase.
		sector_size = 0
		total_size = self.memory_capacity
		page_size = 256
		if sector_size == 0:
			sector_size = self.find_erase_sector_size()
			
		print "Sector size is %d" % sector_size
		erase_sectors = [0]*(total_size/sector_size)
		sector_list = []
		for seg in f.segments:
			start_sector = seg.start_address/sector_size
			if erase_sectors[start_sector] == 0:
				erase_sectors[start_sector] = 1
				sector_list.append(start_sector)
			end_address = seg.end_address
			end_sector = start_sector + 1
			while end_sector*sector_size < seg.end_address:
				if erase_sectors[end_sector] == 0:
					erase_sectors[end_sector] = 1
					sector_list.append(end_sector)
				end_sector = end_sector + 1
		count=0
		total=len(sector_list)
		print "Erasing %d sectors." % total
		SPI.update_progress(0)
		for erase in sector_list:
			self.erase(erase*sector_size)
			count=count+1
			SPI.update_progress(float(count)/float(total))
		seg_count=0
		for seg in f.segments:
			start = seg.start_address
			end = 0
			print "Programming segment %d/%d." % (seg_count+1 , len(f.segments))
			SPI.update_progress(0)
			while start < seg.size:
				end = start + page_size
				if end > seg.end_address:
					end = seg.end_address
				data = seg[start:end].data
				self.page_program(start, data)
				start = end
				SPI.update_progress(float(start)/float(seg.size))
				
		self.write_disable()
		print "Complete!"

	def page_program(self, address, data_write = []):
		self.write_enable()
		data_write.insert(0,(address & 0xFF))
		data_write.insert(0,((address>>8) & 0xFF))
		data_write.insert(0,((address>>16) & 0xFF))
		if self.memory_capacity > 2**24:
			data_write.insert(0,((address>>24) & 0xFF))
			self.command(self.cmd["4PP"],0,0,data_write)
		else:
			self.command(self.cmd["3PP"],0,0,data_write)
		res = self.status()
		trials = 0
		while trials < 10:
			res = self.status()
			if res & 0x1:
				break
			trials = trials + 1
		trials = 0
		while res & 0x1:
			res = self.status()
			trials = trials + 1

	def erase(self, address): 
		self.write_enable()
		if self.memory_capacity > 2**24:
			data = []
			data.append((address >> 24) & 0xFF)
			data.append((address >> 16) & 0xFF)
			data.append((address >> 8) & 0xFF)
			data.append((address & 0xFF))
			erase = self.command(self.cmd["4SE"], 0, 0, data)
		else:
			data = []
			data.append((address>>16) & 0xFF)
			data.append((address>>8) & 0xFF)
			data.append((address & 0xFF))
			erase = self.command(self.cmd["3SE"], 0, 0, data)
		res = self.status()
		trials = 0
		while trials < 10:
			res = self.status()
			if res & 0x1:
				break
		if trials == 10:
			print "Erase did not start (res=%x)!" % res
			return
		trials = 0
		while res & 0x1:
			res = self.status()
			trials = trials + 1

	def write_bank_address(self, bank):
		if self.memory_capacity > 2**24:
			return
		bank_write = self.command(self.cmd["BRWR"], 0, 0, [ bank ])
		return bank_write 	
		
	def read_bank_address(self):
		if self.memory_capacity > 2**24:
			res = []
			res.append(0)
			return res
		bank_read = self.command(self.cmd["BRRD"], 0, 1)
		return bank_read
		