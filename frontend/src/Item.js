import React, { useState } from 'react';
import ModelPage from './ModelPage';
import './Item.css';

const Item = (props) => {
    const [showModel, setShowModel] = useState(false);
    // const { item } = props;
    const [expanded, setExpanded] = useState(false);
    const item = props;
    const handleClick = () => {
        setExpanded(!expanded);
    }
    return (
        <div key={item.name} className={`item ${expanded ? 'expanded' : ''}`} onClick={handleClick}>
            <div className="item-header">
                <h3>{item.name}</h3>
            </div>
            <div className="item-description">
                <p>{item.description}</p>
            </div>
            <div className="item-footer">
                <button onClick={() => setShowModel(!showModel)}>View Model</button>
            </div>
            {showModel && <ModelPage model={item} onClose={() => setShowModel(false)} />}
        </div>
    )
}




export default Item;
