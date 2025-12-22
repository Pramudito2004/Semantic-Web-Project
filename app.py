from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

# Fuseki SPARQL Endpoint
FUSEKI_ENDPOINT = "http://localhost:3030/teman-klinik/query"
PREFIX = """
PREFIX : <http://www.semanticweb.org/ontologies/2025/0/teman-klinik/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""

def execute_sparql(query):
    """Execute SPARQL query to Fuseki"""
    full_query = PREFIX + query
    response = requests.post(
        FUSEKI_ENDPOINT,
        data={'query': full_query},
        headers={'Accept': 'application/sparql-results+json'}
    )
    if response.status_code == 200:
        return response.json()
    return None

@app.route('/')
def index():
    """Home page - get all options for checkboxes"""
    # Get all gejala
    gejala_query = """
    SELECT ?gejala ?nama ?urgensi ?tingkat WHERE {
        ?gejala a :Gejala ;
                rdfs:label ?nama .
        OPTIONAL { ?gejala :tingkatUrgensity ?urgensi }
        OPTIONAL { ?gejala :memilikiTingkatKeparahan ?tk . ?tk rdfs:label ?tingkat }
    } ORDER BY ?nama
    """
    
    # Get all kondisi pasien
    kondisi_query = """
    SELECT ?kondisi ?nama WHERE {
        ?kondisi a :KelompokPasien ;
                 rdfs:label ?nama .
    } ORDER BY ?nama
    """
    
    # Get all bahan aktif (untuk alergi)
    alergi_query = """
    SELECT ?bahan ?nama WHERE {
        ?bahan a :BahanAktif ;
               rdfs:label ?nama .
    } ORDER BY ?nama
    """
    
    gejala_result = execute_sparql(gejala_query)
    kondisi_result = execute_sparql(kondisi_query)
    alergi_result = execute_sparql(alergi_query)
    
    gejala_list = []
    if gejala_result:
        for item in gejala_result['results']['bindings']:
            gejala_list.append({
                'uri': item['gejala']['value'].split('/')[-1],
                'nama': item['nama']['value'],
                'urgensi': item.get('urgensi', {}).get('value', '1'),
                'tingkat': item.get('tingkat', {}).get('value', 'Ringan')
            })
    
    kondisi_list = []
    if kondisi_result:
        for item in kondisi_result['results']['bindings']:
            kondisi_list.append({
                'uri': item['kondisi']['value'].split('/')[-1],
                'nama': item['nama']['value']
            })
    
    alergi_list = []
    if alergi_result:
        for item in alergi_result['results']['bindings']:
            alergi_list.append({
                'uri': item['bahan']['value'].split('/')[-1],
                'nama': item['nama']['value']
            })
    
    return render_template('index.html', 
                         gejala_list=gejala_list,
                         kondisi_list=kondisi_list,
                         alergi_list=alergi_list)

@app.route('/rekomendasi', methods=['POST'])
def rekomendasi():
    """Process recommendation based on user input"""
    data = request.json
    gejala_selected = data.get('gejala', [])
    kondisi_selected = data.get('kondisi', [])
    alergi_selected = data.get('alergi', [])
    
    if not gejala_selected:
        return jsonify({'error': 'Pilih minimal 1 gejala'})
    
    # Build SPARQL query for recommendations
    gejala_values = ' '.join([f':{g}' for g in gejala_selected])
    
    # Query 1: Get obat yang meredakan gejala yang dipilih
    obat_query = f"""
    SELECT DISTINCT ?obat ?namaObat ?deskripsi ?dosis ?caraPakai ?harga ?golongan ?bentuk ?peringatan ?contohMerek
           (GROUP_CONCAT(DISTINCT ?gejalaLabel; separator=", ") as ?untukGejala)
    WHERE {{
        VALUES ?gejala {{ {gejala_values} }}
        ?gejala :diredakanOleh ?obat .
        ?obat rdfs:label ?namaObat .
        OPTIONAL {{ ?obat :deskripsiSingkat ?deskripsi }}
        OPTIONAL {{ ?obat :dosisObat ?dosis }}
        OPTIONAL {{ ?obat :caraPakai ?caraPakai }}
        OPTIONAL {{ ?obat :hargaObat ?harga }}
        OPTIONAL {{ ?obat :golonganObat ?golongan }}
        OPTIONAL {{ ?obat :bentukSediaan ?bentuk }}
        OPTIONAL {{ ?obat :peringatan ?peringatan }}
        OPTIONAL {{ ?obat :contohMerek ?contohMerek }}
        ?gejala rdfs:label ?gejalaLabel .
    }}
    GROUP BY ?obat ?namaObat ?deskripsi ?dosis ?caraPakai ?harga ?golongan ?bentuk ?peringatan ?contohMerek
    """
    
    obat_result = execute_sparql(obat_query)
    
    # Query 2: Get obat yang harus dihindari berdasarkan kondisi
    excluded_obat = set()
    excluded_reasons = {}
    
    if kondisi_selected:
        kondisi_values = ' '.join([f':{k}' for k in kondisi_selected])
        exclude_query = f"""
        SELECT ?obat ?namaObat ?kondisiNama WHERE {{
            VALUES ?kondisi {{ {kondisi_values} }}
            ?obat :tidakBolehUntuk ?kondisi .
            ?obat rdfs:label ?namaObat .
            ?kondisi rdfs:label ?kondisiNama .
        }}
        """
        exclude_result = execute_sparql(exclude_query)
        if exclude_result:
            for item in exclude_result['results']['bindings']:
                obat_uri = item['obat']['value'].split('/')[-1]
                excluded_obat.add(obat_uri)
                excluded_reasons[obat_uri] = {
                    'nama': item['namaObat']['value'],
                    'alasan': f"Tidak boleh untuk {item['kondisiNama']['value']}"
                }
    
    # Query 3: Get obat yang mengandung bahan alergi
    if alergi_selected:
        alergi_values = ' '.join([f':{a}' for a in alergi_selected])
        alergi_exclude_query = f"""
        SELECT ?obat ?namaObat ?bahanNama WHERE {{
            VALUES ?bahan {{ {alergi_values} }}
            ?obat :mengandungBahanAktif ?bahan .
            ?obat rdfs:label ?namaObat .
            ?bahan rdfs:label ?bahanNama .
        }}
        """
        alergi_exclude_result = execute_sparql(alergi_exclude_query)
        if alergi_exclude_result:
            for item in alergi_exclude_result['results']['bindings']:
                obat_uri = item['obat']['value'].split('/')[-1]
                excluded_obat.add(obat_uri)
                excluded_reasons[obat_uri] = {
                    'nama': item['namaObat']['value'],
                    'alasan': f"Mengandung {item['bahanNama']['value']} (alergi)"
                }
    
    # Query 4: Get alternatif herbal (use meredakanGejala since Fuseki doesn't auto-infer inverse)
    alternatif_query = f"""
    SELECT DISTINCT ?obat ?namaObat ?deskripsi ?dosis ?harga WHERE {{
        VALUES ?gejala {{ {gejala_values} }}
        ?obat :meredakanGejala ?gejala .
        ?obat a :PengobatanAlternatif ;
              rdfs:label ?namaObat .
        OPTIONAL {{ ?obat :deskripsiSingkat ?deskripsi }}
        OPTIONAL {{ ?obat :dosisObat ?dosis }}
        OPTIONAL {{ ?obat :hargaObat ?harga }}
    }}
    """
    alternatif_result = execute_sparql(alternatif_query)
    
    # Process results
    rekomendasi_list = []
    if obat_result:
        for item in obat_result['results']['bindings']:
            obat_uri = item['obat']['value'].split('/')[-1]
            if obat_uri not in excluded_obat:
                rekomendasi_list.append({
                    'nama': item['namaObat']['value'],
                    'deskripsi': item.get('deskripsi', {}).get('value', '-'),
                    'dosis': item.get('dosis', {}).get('value', '-'),
                    'caraPakai': item.get('caraPakai', {}).get('value', '-'),
                    'harga': item.get('harga', {}).get('value', '-'),
                    'golongan': item.get('golongan', {}).get('value', '-'),
                    'bentuk': item.get('bentuk', {}).get('value', '-'),
                    'peringatan': item.get('peringatan', {}).get('value', ''),
                    'untukGejala': item.get('untukGejala', {}).get('value', '-'),
                    'contohMerek': item.get('contohMerek', {}).get('value', '')
                })
    
    alternatif_list = []
    if alternatif_result:
        for item in alternatif_result['results']['bindings']:
            alternatif_list.append({
                'nama': item['namaObat']['value'],
                'deskripsi': item.get('deskripsi', {}).get('value', '-'),
                'dosis': item.get('dosis', {}).get('value', '-'),
                'harga': item.get('harga', {}).get('value', '-')
            })
    
    # Check for severe symptoms warning
    warning = None
    urgensi_query = f"""
    SELECT ?gejala ?nama ?urgensi WHERE {{
        VALUES ?gejala {{ {gejala_values} }}
        ?gejala rdfs:label ?nama ;
                :tingkatUrgensity ?urgensi .
        FILTER (?urgensi >= 4)
    }}
    """
    urgensi_result = execute_sparql(urgensi_query)
    if urgensi_result and urgensi_result['results']['bindings']:
        gejala_berat = [item['nama']['value'] for item in urgensi_result['results']['bindings']]
        warning = f"⚠️ PERINGATAN: Gejala {', '.join(gejala_berat)} termasuk BERAT. Segera konsultasi ke dokter!"
    
    return jsonify({
        'rekomendasi': rekomendasi_list,
        'excluded': list(excluded_reasons.values()),
        'alternatif': alternatif_list,
        'warning': warning
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
