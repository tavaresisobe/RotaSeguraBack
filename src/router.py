import osmnx as ox
import networkx as nx
import pandas as pd
import folium
import traceback
from src.db import get_mongo_connection
from src.settings import COL_ESTATISTICAS, DB_NAME, MONGO_URI, PLACE_NAME

# --- Configurações da Cidade ---
print(f"Carregando grafo de ruas para {PLACE_NAME}...")
graph = ox.graph_from_place(PLACE_NAME, network_type='drive', retain_all=False, truncate_by_edge=True)
graph = ox.add_edge_speeds(graph)
graph = ox.add_edge_travel_times(graph)
print("Grafo carregado e processado.")

# --- Função de normalização de nome de rua (reutilizável) ---
def normalize_street_name_func(name):
    if isinstance(name, str):
        return name.lower().replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u').replace('ã', 'a').replace('õ', 'o').replace('ç', 'c').strip()
    return name

# --- 2. Função para carregar e processar dados de ocorrências ---
def load_and_process_crime_data():
    try:
        db_connection = get_mongo_connection()
        collection = db_connection[COL_ESTATISTICAS]

        print(f"Conectando ao MongoDB em: {MONGO_URI}, Banco: {DB_NAME}, Coleção: {COL_ESTATISTICAS}")

        crime_documents = list(collection.find({}))

        if not crime_documents:
            print(f"Aviso: Nenhuns dados de ocorrências criminosas encontrados na coleção '{COL_ESTATISTICAS}'. As rotas não serão filtradas por crimes.")
            return {}

        df_crimes = pd.DataFrame(crime_documents)
        df_crimes['LOGRADOURO_NORMALIZADO'] = df_crimes['LOGRADOURO'].apply(normalize_street_name_func)
        df_crimes.dropna(subset=['LOGRADOURO_NORMALIZADO', 'total_ocorrencias'], inplace=True)

        crime_counts = df_crimes.set_index('LOGRADOURO_NORMALIZADO')['total_ocorrencias'].fillna(0).to_dict()

        print(f"Dados de ocorrências processados. {len(crime_counts)} ruas com contagem de crimes.")
        return crime_counts

    except Exception as e:
        print(f"Erro ao conectar ou carregar dados do MongoDB: {e}")
        return {}

CRIME_DATA = load_and_process_crime_data()

# --- 3. Função para geocodificar nomes de ruas ---
def get_node_by_street_name(graph, street_name, city_name=PLACE_NAME):
    try:
        location = ox.geocode(f"{street_name}, {city_name}")
        node = ox.distance.nearest_nodes(graph, location[1], location[0])
        return node
    except Exception as e:
        print(f"Erro ao geocodificar ou encontrar nó para a rua '{street_name}': {e}")
        return None

# --- 4. Algoritmo de cálculo de rota com filtro de segurança ---
def calculate_safe_route(
    origin_street: str,
    destination_street: str,
    max_crime_occurrences: int,
    _graph=graph,
    _crime_data=CRIME_DATA
) -> dict:

    orig_node = get_node_by_street_name(_graph, origin_street)
    dest_node = get_node_by_street_name(_graph, destination_street)

    if orig_node is None:
        return {"error": f"Não foi possível encontrar a rua de origem: '{origin_street}'. Verifique a grafia.", "route_map_html": None}
    if dest_node is None:
        return {"error": f"Não foi possível encontrar a rua de destino: '{destination_street}'. Verifique a grafia.", "route_map_html": None}

    G_filtered = _graph.copy()
    edges_to_remove = []
    removed_edges_details = []

    for u, v, k, data in G_filtered.edges(keys=True, data=True):
        street_names_from_osm = data.get('name')

        if isinstance(street_names_from_osm, str):
            street_names_list = [street_names_from_osm]
        elif isinstance(street_names_from_osm, list):
            street_names_list = street_names_from_osm
        else:
            street_names_list = []

        highest_crime_count_for_edge = 0 
        should_remove_this_edge = False

        for name_osm in street_names_list:
            normalized_name_osm = normalize_street_name_func(name_osm)
            crime_count_from_db = _crime_data.get(normalized_name_osm, 0)

            if crime_count_from_db > highest_crime_count_for_edge:
                highest_crime_count_for_edge = crime_count_from_db

            if crime_count_from_db > max_crime_occurrences:
                should_remove_this_edge = True
                break 

        if should_remove_this_edge:
            edges_to_remove.append((u, v, k))
            removed_edges_details.append({"names": street_names_list, "crime_count": highest_crime_count_for_edge, "original_edge_id": (u,v,k)})

    if edges_to_remove:
        G_filtered.remove_edges_from(edges_to_remove)
        print(f"Removidas {len(edges_to_remove)} arestas devido ao limite de ocorrências ({max_crime_occurrences}).")
    else:
        print("Nenhuma aresta removida, todas as ruas estão dentro do limite de ocorrências ou não têm dados de crime.")

    try:
        route_nodes = nx.shortest_path(G_filtered, orig_node, dest_node, weight='travel_time')
        gdf_route_edges = ox.routing.route_to_gdf(_graph, route_nodes, weight='travel_time')

        route_street_names = []
        for name_data in gdf_route_edges['name'].tolist():
            if isinstance(name_data, str):
                route_street_names.append(name_data)
            elif isinstance(name_data, list):
                route_street_names.extend(name_data)

        cleaned_street_names = []
        if route_street_names:
            cleaned_street_names.append(route_street_names[0])
            for i in range(1, len(route_street_names)):
                if route_street_names[i] != route_street_names[i-1]:
                    cleaned_street_names.append(route_street_names[i])

        route_street_info = []
        for nome in cleaned_street_names:
            nome_normalizado = normalize_street_name_func(nome)
            ocorrencias = _crime_data.get(nome_normalizado, 0)
            route_street_info.append({
                "nome": nome,
                "ocorrencias": ocorrencias,
                "periodo": "N/A"
            })

        if orig_node in _graph.nodes and dest_node in _graph.nodes:
            center_lat = (_graph.nodes[orig_node]['y'] + _graph.nodes[dest_node]['y']) / 2
            center_lon = (_graph.nodes[orig_node]['x'] + _graph.nodes[dest_node]['x']) / 2
            route_map = folium.Map(location=[center_lat, center_lon], zoom_start=12)

            folium.Marker(
                location=[_graph.nodes[orig_node]['y'], _graph.nodes[orig_node]['x']],
                popup=f"Origem: {origin_street}",
                icon=folium.Icon(color="green", icon="play")
            ).add_to(route_map)
            folium.Marker(
                location=[_graph.nodes[dest_node]['y'], _graph.nodes[dest_node]['x']],
                popup=f"Destino: {destination_street}",
                icon=folium.Icon(color="red", icon="stop")
            ).add_to(route_map)

            route_coords = [( _graph.nodes[node_id]['y'], _graph.nodes[node_id]['x']) for node_id in route_nodes]

            folium.PolyLine(
                locations=route_coords, color="blue", weight=5, opacity=0.7, tooltip="Rota Segura"
            ).add_to(route_map)

            if removed_edges_details and len(removed_edges_details) < 500:
                for removed_detail in removed_edges_details:
                    u, v, k = removed_detail['original_edge_id']
                    edge_data_k = _graph.get_edge_data(u, v, k)

                    if edge_data_k and 'geometry' in edge_data_k:
                        if edge_data_k['geometry'].geom_type == 'LineString':
                            coords = [(lat, lon) for lon, lat in edge_data_k['geometry'].coords]
                            name_tooltip = ", ".join(removed_detail['names']) if removed_detail['names'] else "Sem nome"
                            crime_count_tooltip = removed_detail['crime_count']
                            folium.PolyLine(
                                locations=coords, color='orange', weight=3, opacity=0.5,
                                tooltip=f"Rua Evitada: {name_tooltip} ({crime_count_tooltip} crimes)"
                            ).add_to(route_map)

            map_html = route_map._repr_html_()
        else:
            map_html = "Não foi possível gerar o mapa: Nós de origem/destino inválidos."

        return {
            "route_found": True,
            "route_street_names": cleaned_street_names,
            "route_street_info": route_street_info,
            "route_map_html": map_html,
            "message": "Rota segura encontrada!"
        }

    except nx.NetworkXNoPath as e:
        return {
            "route_found": False,
            "message": f"Não foi possível encontrar uma rota com o limite de ocorrências. Tente aumentar o limite."
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Ocorreu um erro inesperado: {e}", "route_map_html": None}
